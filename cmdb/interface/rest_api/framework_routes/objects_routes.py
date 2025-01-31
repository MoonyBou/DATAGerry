# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2024 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Definition of all routes for objects
"""
import json
import copy
import logging
from typing import List
from datetime import datetime, timezone
from bson import json_util
from flask import abort, jsonify, request, current_app

from cmdb.framework.managers.object_manager import ObjectManager
from cmdb.framework.cmdb_object_manager import CmdbObjectManager
from cmdb.framework.managers.type_manager import TypeManager
from cmdb.user_management import UserModel, UserManager
from cmdb.manager.object_links_manager import ObjectLinksManager
from cmdb.manager.locations_manager import LocationsManager
from cmdb.manager.logs_manager import LogsManager

from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.database.utils import object_hook, default
from cmdb.framework import CmdbObject, TypeModel
from cmdb.framework.cmdb_errors import ObjectDeleteError, ObjectInsertError, ObjectManagerGetError, \
    ObjectManagerUpdateError
from cmdb.framework.models.log import LogAction, CmdbObjectLog
from cmdb.framework import ObjectLinkModel
from cmdb.framework.cmdb_render import CmdbRender, RenderList, RenderError
from cmdb.framework.results import IterationResult
from cmdb.framework.utils import Model
from cmdb.interface.api_parameters import CollectionParameters
from cmdb.interface.response import GetMultiResponse, GetListResponse, UpdateMultiResponse, UpdateSingleResponse,\
    ResponseFailedMessage, ErrorBody
from cmdb.interface.route_utils import make_response, insert_request_user
from cmdb.interface.blueprint import APIBlueprint
from cmdb.security.acl.errors import AccessDeniedError
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.manager import ManagerIterationError, ManagerGetError, ManagerUpdateError
from cmdb.utils.error import CMDBError

from cmdb.errors.manager import ManagerInsertError

from cmdb.framework import CmdbLocation
# -------------------------------------------------------------------------------------------------------------------- #

objects_blueprint = APIBlueprint('objects', __name__)

LOGGER = logging.getLogger(__name__)

with current_app.app_context():
    object_manager = CmdbObjectManager(current_app.database_manager, current_app.event_queue)
    manager = ObjectManager(database_manager=current_app.database_manager)
    type_manager = TypeManager(database_manager=current_app.database_manager)
    user_manager = UserManager(current_app.database_manager)
    object_links_manager = ObjectLinksManager(current_app.database_manager, current_app.event_queue)
    locations_manager = LocationsManager(current_app.database_manager, current_app.event_queue)
    logs_manager = LogsManager(current_app.database_manager, current_app.event_queue)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@objects_blueprint.route('/', methods=['POST'])
@objects_blueprint.protect(auth=True, right='base.framework.object.add')
@insert_request_user
def insert_object(request_user: UserModel):
    """TODO: document"""
    add_data_dump = json.dumps(request.json)
    try:
        new_object_data = json.loads(add_data_dump, object_hook=json_util.object_hook)

        if 'public_id' not in new_object_data:
            new_object_data['public_id'] = object_manager.get_new_id(CmdbObject.COLLECTION)
        else:
            try:
                object_manager.get_object(public_id=new_object_data['public_id'])
            except ObjectManagerGetError:
                pass
            else:
                return abort(400, f'Type with PublicID {new_object_data["public_id"]} already exists.')

        if 'active' not in new_object_data:
            new_object_data['active'] = True

        new_object_data['creation_time'] = datetime.now(timezone.utc)
        new_object_data['views'] = 0
        new_object_data['version'] = '1.0.0'  # default init version

        new_object_id = object_manager.insert_object(new_object_data,
                                                     user=request_user,
                                                     permission=AccessControlPermission.CREATE)
        # get current object state
        current_type_instance = object_manager.get_type(new_object_data['type_id'])
        current_object = object_manager.get_object(new_object_id)

        current_object_render_result = CmdbRender(object_instance=current_object,
                                                  object_manager=object_manager,
                                                  type_instance=current_type_instance,
                                                  render_user=request_user).result()

        # Generate new insert log
        try:
            log_params = {
                'object_id': new_object_id,
                'user_id': request_user.get_public_id(),
                'user_name': request_user.get_display_name(),
                'comment': 'Object was created',
                'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8'),
                'version': current_object.version
            }

            logs_manager.insert_log(action=LogAction.CREATE, log_type=CmdbObjectLog.__name__, **log_params)
        except ManagerInsertError as err:
            LOGGER.error("ManagerInsertError: %s", err)

    except (TypeError, ObjectInsertError) as err:
        LOGGER.error(err)
        return abort(400, str(err))
    except (ManagerGetError, ObjectManagerGetError) as err:
        LOGGER.error(err)
        return abort(404, err.message)
    except AccessDeniedError as err:
        return abort(403, err.message)
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    return make_response(new_object_id)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@objects_blueprint.route('/<int:public_id>', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@insert_request_user
def get_object(public_id, request_user: UserModel):
    """TODO: document"""
    try:
        object_instance = object_manager.get_object(public_id,
                                                    user=request_user,
                                                    permission=AccessControlPermission.READ)
    except (ObjectManagerGetError, ManagerGetError) as err:
        return abort(404, err.message)
    except AccessDeniedError as err:
        return abort(403, err.message)

    try:
        type_instance = TypeManager(database_manager=current_app.database_manager).get(object_instance.get_type_id())
    except ObjectManagerGetError as err:
        LOGGER.error(err.message)
        return abort(404, err.message)

    try:
        render = CmdbRender(object_instance=object_instance,
                            type_instance=type_instance,
                            render_user=request_user,
                            object_manager=object_manager,
                            ref_render=True)

        render_result = render.result()
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    return make_response(render_result)


@objects_blueprint.route('/', methods=['GET', 'HEAD'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@objects_blueprint.parse_collection_parameters(view='native')
@insert_request_user
def get_objects(params: CollectionParameters, request_user: UserModel):
    """
    Retrieves multiple objects from db regarding the used params

    Args:
        params (CollectionParameters): Parameters for which objects and how they should be returned
        request_user (UserModel): User requesting this operation

    Returns:
        (Response): The objects from db fitting the params
    """
    view = params.optional.get('view', 'native')

    if _fetch_only_active_objs():
        if isinstance(params.filter, dict):
            params.filter = [{'$match': params.filter}]
            params.filter.append({'$match': {'active': {"$eq": True}}})
        elif isinstance(params.filter, list):
            params.filter.append({'$match': {'active': {"$eq": True}}})

    try:
        iteration_result: IterationResult[CmdbObject] = manager.iterate(
                                                        filter=params.filter,
                                                        limit=params.limit,
                                                        skip=params.skip,
                                                        sort=params.sort,
                                                        order=params.order,
                                                        user=request_user,
                                                        permission=AccessControlPermission.READ)

        if view == 'native':
            object_list: List[dict] = [object_.__dict__ for object_ in iteration_result.results]

            api_response = GetMultiResponse(object_list,
                                            total=iteration_result.total,
                                            params=params,
                                            url=request.url,
                                            model=CmdbObject.MODEL,
                                            body=request.method == 'HEAD')
        elif view == 'render':
            rendered_list = RenderList(object_list=iteration_result.results,
                                       request_user=request_user,
                                       database_manager=current_app.database_manager,
                                       object_manager=object_manager,
                                       ref_render=True).render_result_list(raw=True)

            api_response = GetMultiResponse(rendered_list,
                                            total=iteration_result.total,
                                            params=params,
                                            url=request.url,
                                            model=Model('RenderResult'),
                                            body=request.method == 'HEAD')
        else:
            return abort(401, 'No possible view parameter')

    except ManagerIterationError as err:
        return abort(400, err)
    except ManagerGetError as err:
        return abort(404, err)

    return api_response.make_response()


@objects_blueprint.route('/<int:public_id>/native', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@insert_request_user
def get_native_object(public_id: int, request_user: UserModel):
    """TODO: document"""
    try:
        object_instance = object_manager.get_object(public_id,
                                                    user=request_user,
                                                    permission=AccessControlPermission.READ)
    except ObjectManagerGetError:
        return abort(404)
    except AccessDeniedError as err:
        return abort(403, err.message)

    return make_response(object_instance)


@objects_blueprint.route('/group/<string:value>', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@insert_request_user
def group_objects_by_type_id(value, request_user: UserModel):
    """TODO: document"""
    try:
        filter_state = None
        if _fetch_only_active_objs():
            filter_state = {'active': {"$eq": True}}
        result = []
        cursor = object_manager.group_objects_by_value(value,
                                                       filter_state,
                                                       user=request_user,
                                                       permission=AccessControlPermission.READ)
        max_length = 0
        for document in cursor:
            document['label'] = object_manager.get_type(document['_id']).label
            result.append(document)
            max_length += 1
            if max_length == 5:
                break

    except CMDBError:
        return abort(400)
    return make_response(result)


@objects_blueprint.route('/<int:public_id>/mds_reference', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@insert_request_user
def get_object_mds_reference(public_id: int, request_user: UserModel):
    """TODO: document"""
    try:
        referenced_object: CmdbObject = manager.get(public_id,
                                                    user=request_user,
                                                    permission=AccessControlPermission.READ)

        referenced_type: TypeModel = type_manager.get(referenced_object.get_type_id())

    except ManagerGetError as err:
        return abort(404, err)

    try:
        mds_reference = CmdbRender(object_instance=referenced_object,
                    type_instance=referenced_type,
                    render_user=request_user,
                    object_manager=object_manager,
                    ref_render=True).get_mds_reference(public_id)

    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    return make_response(mds_reference)



@objects_blueprint.route('/<int:public_id>/mds_references', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@insert_request_user
def get_object_mds_references(public_id: int, request_user: UserModel):
    """TODO: document"""
    summary_lines = {}

    object_id_list = request.args.get('objectIDs').split(",")
    object_ids = [int(obj_id) for obj_id in object_id_list]

    if not len(object_ids) > 0:
        object_ids = [public_id]

    for object_id in object_ids:
        try:
            referenced_object: CmdbObject = manager.get(object_id,
                                                        user=request_user,
                                                        permission=AccessControlPermission.READ)

            referenced_type: TypeModel = type_manager.get(referenced_object.get_type_id())

        except ManagerGetError as err:
            return abort(404, err)

        try:
            mds_reference = CmdbRender(object_instance=referenced_object,
                        type_instance=referenced_type,
                        render_user=request_user,
                        object_manager=object_manager,
                        ref_render=True).get_mds_reference(object_id)

            summary_lines[object_id] = mds_reference

        except RenderError as err:
            LOGGER.error(err)
            return abort(500)

    return make_response(summary_lines)


@objects_blueprint.route('/<int:public_id>/references', methods=['GET', 'HEAD'])
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
@objects_blueprint.parse_collection_parameters(view='native')
@insert_request_user
def get_object_references(public_id: int, params: CollectionParameters, request_user: UserModel):
    """TODO: document"""
    view = params.optional.get('view', 'native')

    if _fetch_only_active_objs():
        if isinstance(params.filter, dict):
            params.filter.update({'$match': {'active': {"$eq": True}}})
        elif isinstance(params.filter, list):
            params.filter.append({'$match': {'active': {"$eq": True}}})
    else:
        if isinstance(params.filter, dict):
            params.filter.update({'$match': {}})
        elif isinstance(params.filter, list):
            params.filter.append({'$match': {}})

    try:
        referenced_object: CmdbObject = manager.get(public_id,
                                                    user=request_user,
                                                    permission=AccessControlPermission.READ)
    except ManagerGetError as err:
        return abort(404, err)
    except AccessDeniedError as err:
        return abort(403, err.message)

    try:
        iteration_result: IterationResult[CmdbObject] = manager.references(
                                                                    object_=referenced_object,
                                                                    filter=params.filter,
                                                                    limit=params.limit,
                                                                    skip=params.skip,
                                                                    sort=params.sort,
                                                                    order=params.order,
                                                                    user=request_user,
                                                                    permission=AccessControlPermission.READ)

        if view == 'native':
            object_list: List[dict] = [object_.__dict__ for object_ in iteration_result.results]
            api_response = GetMultiResponse(object_list, total=iteration_result.total, params=params,
                                            url=request.url, model=CmdbObject.MODEL, body=request.method == 'HEAD')
        elif view == 'render':
            rendered_list = RenderList(object_list=iteration_result.results, request_user=request_user,
                                       database_manager=current_app.database_manager,
                                       object_manager=object_manager, ref_render=True).render_result_list(
                raw=True)

            api_response = GetMultiResponse(rendered_list, total=iteration_result.total, params=params,
                                            url=request.url, model=Model('RenderResult'), body=request.method == 'HEAD')
        else:
            return abort(401, 'No possible view parameter')
    except ManagerIterationError as err:
        return abort(400, err)

    return api_response.make_response()


@objects_blueprint.route('/<int:public_id>/state', methods=['GET'])
@objects_blueprint.protect(auth=True, right='base.framework.object.activation')
@insert_request_user
def get_object_state(public_id: int, request_user: UserModel):
    """TODO: document"""
    try:
        found_object = object_manager.get_object(public_id=public_id,
                                                 user=request_user,
                                                 permission=AccessControlPermission.READ)
    except ObjectManagerGetError as err:
        LOGGER.debug(err)
        return abort(404)
    return make_response(found_object.active)


@objects_blueprint.route('/clean/<int:public_id>', methods=['GET', 'HEAD'])
@objects_blueprint.protect(auth=True, right='base.framework.type.clean')
@insert_request_user
def get_unstructured_objects(public_id: int, request_user: UserModel):
    """
    HTTP `GET`/`HEAD` route for a multi resources which are not formatted according the type structure.
    Args:
        public_id (int): Public ID of the type.
    Raises:
        ManagerGetError: When the selected type does not exists or the objects could not be loaded.
    Returns:
        GetListResponse: Which includes the json data of multiple objects.
    """
    try:
        type_instance: TypeModel = type_manager.get(public_id=public_id)
        objects: List[CmdbObject] = manager.iterate({'type_id': public_id},
                                                    limit=0,
                                                    skip=0,
                                                    sort='public_id',
                                                    order=1,
                                                    user=request_user).results
    except ManagerGetError as err:
        return abort(400, err)

    type_fields = sorted([field.get('name') for field in type_instance.fields])
    unstructured: List[dict] = []

    for object_ in objects:
        object_fields = [field.get('name') for field in object_.fields]
        if sorted(object_fields) != type_fields:
            unstructured.append(object_.__dict__)

    api_response = GetListResponse(unstructured, url=request.url, model=CmdbObject.MODEL, body=request.method == 'HEAD')
    return api_response.make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@objects_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@objects_blueprint.protect(auth=True, right='base.framework.object.edit')
@objects_blueprint.validate(CmdbObject.SCHEMA)
@insert_request_user
def update_object(public_id: int, data: dict, request_user: UserModel):
    """TODO: document"""
    object_ids = request.args.getlist('objectIDs')

    if len(object_ids) > 0:
        object_ids = list(map(int, object_ids))
    else:
        object_ids = [public_id]

    results: list[dict] = []
    failed = []

    for obj_id in object_ids:
        # deep copy
        active_state = request.get_json().get('active', None)
        new_data = copy.deepcopy(data)
        try:
            current_object_instance = manager.get(obj_id, user=request_user, permission=AccessControlPermission.READ)
            current_type_instance = type_manager.get(current_object_instance.get_type_id())
            current_object_render_result = CmdbRender(object_instance=current_object_instance,
                                                      object_manager=object_manager,
                                                      type_instance=current_type_instance,
                                                      render_user=request_user).result()
            update_comment = ''
            try:
                # check for comment
                new_data['public_id'] = obj_id
                new_data['creation_time'] = current_object_instance.creation_time
                new_data['author_id'] = current_object_instance.author_id
                new_data['active'] = active_state if active_state in [True, False] else current_object_instance.active

                if 'version' not in data:
                    new_data['version'] = current_object_instance.version

                old_fields = list(map(lambda x: {k: v for k, v in x.items() if k in ['name', 'value']},
                                      current_object_render_result.fields))
                new_fields = data['fields']
                for item in new_fields:
                    for old in old_fields:
                        if item['name'] == old['name']:
                            old['value'] = item['value']
                new_data['fields'] = old_fields

                update_comment = data['comment']
                del new_data['comment']

            except (KeyError, IndexError, ValueError):
                update_comment = ''
            except TypeError as err:
                LOGGER.error('Error: %s Object: %s', str(err.args), json.dumps(new_data, default=default))
                failed.append(ResponseFailedMessage(error_message=str(err.args), status=400,
                                                    public_id=obj_id, obj=new_data).to_dict())
                continue

            # update edit time
            new_data['last_edit_time'] = datetime.now(timezone.utc)
            new_data['editor_id'] = request_user.public_id

            update_object_instance = CmdbObject(**json.loads(json.dumps(new_data, default=json_util.default),
                                                             object_hook=object_hook))

            # calc version
            changes = current_object_instance / update_object_instance

            if len(changes['new']) == 1:
                new_data['version'] = update_object_instance.update_version(update_object_instance.VERSIONING_PATCH)
            elif len(changes['new']) == len(update_object_instance.fields):
                new_data['version'] = update_object_instance.update_version(update_object_instance.VERSIONING_MAJOR)
            elif len(changes['new']) > (len(update_object_instance.fields) / 2):
                new_data['version'] = update_object_instance.update_version(update_object_instance.VERSIONING_MINOR)
            else:
                new_data['version'] = update_object_instance.update_version(update_object_instance.VERSIONING_PATCH)

            manager.update(obj_id, new_data, request_user, AccessControlPermission.UPDATE)
            results.append(new_data)

            # Generate log entry
            try:
                log_data = {
                    'object_id': obj_id,
                    'version': update_object_instance.get_version(),
                    'user_id': request_user.get_public_id(),
                    'user_name': request_user.get_display_name(),
                    'comment': update_comment,
                    'changes': changes,
                    'render_state': json.dumps(update_object_instance, default=default).encode('UTF-8')
                }
                logs_manager.insert_log(action=LogAction.EDIT, log_type=CmdbObjectLog.__name__, **log_data)
            except ManagerInsertError as err:
                LOGGER.error("ManagerInsertError: %s", err)

        except AccessDeniedError as err:
            LOGGER.error(err)
            return abort(403)
        except ObjectManagerGetError as err:
            LOGGER.error(err)
            failed.append(ResponseFailedMessage(error_message=err.message, status=400,
                                                public_id=obj_id, obj=new_data).to_dict())
            continue
        except (ManagerGetError, ObjectManagerUpdateError) as err:
            LOGGER.error(err)
            failed.append(ResponseFailedMessage(error_message=err.message, status=404,
                                                public_id=obj_id, obj=new_data).to_dict())
            continue
        except (CMDBError, RenderError) as error:
            LOGGER.warning(error)
            failed.append(ResponseFailedMessage(error_message=str(error.__repr__), status=500,
                                                public_id=obj_id, obj=new_data).to_dict())
            continue

    api_response = UpdateMultiResponse(results=results, failed=failed, url=request.url, model=CmdbObject.MODEL)
    return api_response.make_response()


@objects_blueprint.route('/<int:public_id>/state', methods=['PUT'])
@objects_blueprint.protect(auth=True, right='base.framework.object.activation')
@insert_request_user
def update_object_state(public_id: int, request_user: UserModel):
    """TODO: document"""
    if isinstance(request.json, bool):
        state = request.json
    else:
        return abort(400)
    try:
        found_object = manager.get(public_id=public_id, user=request_user, permission=AccessControlPermission.READ)
    except ObjectManagerGetError as err:
        LOGGER.error(err)
        return abort(404, err.message)

    if found_object.active == state:
        return make_response(False, 204)
    try:
        found_object.active = state
        manager.update(public_id, found_object, user=request_user, permission=AccessControlPermission.UPDATE)
    except AccessDeniedError as err:
        return abort(403, err.message)
    except ObjectManagerUpdateError as err:
        LOGGER.error(err)
        return abort(500, err.message)

        # get current object state
    try:
        current_type_instance = type_manager.get(found_object.get_type_id())
        current_object_render_result = CmdbRender(object_instance=found_object,
                                                  object_manager=object_manager,
                                                  type_instance=current_type_instance,
                                                  render_user=request_user).result()
    except ObjectManagerGetError as err:
        LOGGER.error(err)
        return abort(404)
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    try:
        # generate log
        change = {
            'old': not state,
            'new': state
        }
        log_data = {
            'object_id': public_id,
            'version': found_object.version,
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8'),
            'comment': 'Active status has changed',
            'changes': change,
        }

        logs_manager.insert_log(action=LogAction.ACTIVE_CHANGE, log_type=CmdbObjectLog.__name__, **log_data)
    except ManagerInsertError as err:
        LOGGER.error("ManagerInsertError: %s", err)

    api_response = UpdateSingleResponse(result=found_object.__dict__, url=request.url, model=CmdbObject.MODEL)
    return api_response.make_response()


@objects_blueprint.route('/clean/<int:public_id>', methods=['PUT', 'PATCH'])
@objects_blueprint.protect(auth=True, right='base.framework.type.clean')
@insert_request_user
def update_unstructured_objects(public_id: int, request_user: UserModel):
    """
    HTTP `PUT`/`PATCH` route for a multi resources which will be formatted based on the TypeModel
    Args:
        public_id (int): Public ID of the type.
    Raises:
        ManagerGetError: When the type with the `public_id` was not found.
        ManagerUpdateError: When something went wrong during the update.
    Returns:
        UpdateMultiResponse: Which includes the json data of multiple updated objects.
    """
    try:
        update_type_instance = type_manager.get(public_id)

        type_fields = update_type_instance.fields

        objects_by_type = manager.iterate({'type_id': public_id},
                                          limit=0,
                                          skip=0,
                                          sort='public_id',
                                          order=1,
                                          user=request_user).results

        for obj in objects_by_type:
            incorrect = []
            correct = []
            obj_fields = obj.get_all_fields()
            for t_field in type_fields:
                name = t_field["name"]
                for field in obj_fields:
                    if name == field["name"]:
                        correct.append(field["name"])
                    else:
                        incorrect.append(field["name"])
            removed_type_fields = [item for item in incorrect if not item in correct]
            for field in removed_type_fields:
                manager.update_many(query={'public_id': obj.public_id},
                                    update={'$pull': {'fields': {"name": field}}})

        objects_by_type = manager.iterate({'type_id': public_id}, limit=0, skip=0,
                                          sort='public_id', order=1, user=request_user).results

        for obj in objects_by_type:
            for t_field in type_fields:
                name = t_field["name"]
                value = None
                if [item for item in obj.get_all_fields() if item["name"] == name]:
                    continue
                if "value" in t_field:
                    value = t_field["value"]

                manager.update_many(query={'public_id': obj.public_id},
                                    update={'fields': {"name": name, "value": value}},
                                    add_to_set=True)
    except ManagerUpdateError as err:
        return abort(400, err)

    api_response = UpdateMultiResponse([], url=request.url, model=CmdbObject.MODEL)

    return api_response.make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@objects_blueprint.route('/<int:public_id>', methods=['DELETE'])
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
@insert_request_user
def delete_object(public_id: int, request_user: UserModel):
    """
    Deletes an object and logs the deletion

    Params:
        public_id (int): Public ID of the object which should be deleted
        request_user (UserModel): The user requesting the deletion of the obeject
    Returns:
        Response: Acknowledgment of database 
    """
    current_location = None

    try:
        current_object_instance = object_manager.get_object(public_id)

        # Remove object links and references
        if current_object_instance:
            delete_object_links(public_id)
            manager.delete_all_object_references(public_id)

        current_type_instance = object_manager.get_type(current_object_instance.get_type_id())
        current_object_render_result = CmdbRender(object_instance=current_object_instance,
                                                  object_manager=object_manager,
                                                  type_instance=current_type_instance,
                                                  render_user=request_user).result()

        #an object can not be deleted if it has a location AND the location is a parent for other locations
        try:
            current_location = locations_manager.get_location_for_object(public_id)
            child_location = locations_manager.get_one_by({'parent': current_location.public_id})

            if child_location and len(child_location) > 0:
                return ErrorBody(405, "The location of this object has child locations!").response()
        except ManagerGetError:
            pass

    except ObjectManagerGetError as err:
        LOGGER.error(err)
        return abort(404)
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    try:
        if current_location:
            locations_manager.delete({'public_id':current_location.public_id})

        ack = object_manager.delete_object(public_id, request_user, AccessControlPermission.DELETE)
    except ObjectManagerGetError as err:
        return abort(400, err.message)
    except AccessDeniedError as err:
        return abort(403, err.message)
    except ObjectDeleteError:
        return abort(400)
    except CMDBError:
        return abort(500)

    try:
        # generate log
        log_data = {
            'object_id': public_id,
            'version': current_object_render_result.object_information['version'],
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'comment': 'Object was deleted',
            'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8')
        }
        logs_manager.insert_log(action=LogAction.DELETE, log_type=CmdbObjectLog.__name__, **log_data)
    except ManagerInsertError as err:
        LOGGER.error("ManagerInsertError: %s", err)

    return make_response(ack)


@objects_blueprint.route('/<int:public_id>/locations', methods=['DELETE'])
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
@insert_request_user
def delete_object_with_child_locations(public_id: int, request_user: UserModel):
    """TODO: document"""
    try:
        # check if object exists
        current_object_instance = object_manager.get_object(public_id)

        # Remove object links and references
        if current_object_instance:
            delete_object_links(public_id)
            manager.delete_all_object_references(public_id)

        # check if location for this object exists
        current_location = locations_manager.get_location_for_object(public_id)

        if current_object_instance and current_location:
            # get all child locations for this location
            build_params = BuilderParameters([{"$match":{"public_id":{"$gt":1}}}])

            iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(build_params)

            all_locations: List[dict] = [location_.__dict__ for location_ in iteration_result.results]
            all_children = locations_manager.get_all_children(current_location.public_id, all_locations)

            # delete all child locations
            for child in all_children:
                locations_manager.delete({'public_id':child['public_id']})

            # delete the current object and its location
            locations_manager.delete({'public_id':current_location.public_id})

            deleted = object_manager.delete_object(public_id, request_user, permission=AccessControlPermission.DELETE)

        else:
            # something went wrong, either object or location don't exist
            return abort(404)

    except ObjectManagerGetError as err:
        LOGGER.error(err)
        return abort(404)
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    return make_response(deleted)


@objects_blueprint.route('/<int:public_id>/children', methods=['DELETE'])
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
@insert_request_user
def delete_object_with_child_objects(public_id: int, request_user: UserModel):
    """
    Deletes an object and all objects which are child objects of it in the location tree.
    The corresponding locations of each object are also deleted

    Args:
        public_id (int): public_id of the object which should be deleted with its children
        request_user (UserModel): User requesting this operation

    Returns:
        (int): Success of this operation
    """
    try:
        # check if object exists
        current_object_instance = object_manager.get_object(public_id)

        # Remove object links and references
        if current_object_instance:
            delete_object_links(public_id)
            manager.delete_all_object_references(public_id)

        # check if location for this object exists
        current_location = locations_manager.get_location_for_object(public_id)

        if current_object_instance and current_location:
            # get all child locations for this location
            builder_params = BuilderParameters([{"$match":{"public_id":{"$gt":1}}}])

            iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(builder_params)

            all_locations: List[dict] = [location_.__dict__ for location_ in iteration_result.results]
            all_children_locations = locations_manager.get_all_children(current_location.public_id, all_locations)

            children_object_ids = []

            # delete all child locations and extract their corresponding object_ids
            for child in all_children_locations:
                children_object_ids.append(child['object_id'])
                locations_manager.delete({'public_id':child['public_id']})

            # # delete the objects of child locations
            for child_object_id in children_object_ids:
                object_manager.delete_object(child_object_id, request_user, AccessControlPermission.DELETE)

            # # delete the current object and its location
            locations_manager.delete({'public_id':current_location.public_id})
            deleted = object_manager.delete_object(public_id, request_user, AccessControlPermission.DELETE)

        else:
            # something went wrong, either object or location don't exist
            return abort(404)

    except ObjectManagerGetError as err:
        LOGGER.error(err)
        return abort(404)
    except RenderError as err:
        LOGGER.error(err)
        return abort(500)

    return make_response(deleted)


@objects_blueprint.route('/delete/<string:public_ids>', methods=['DELETE'])
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
@insert_request_user
def delete_many_objects(public_ids, request_user: UserModel):
    """TODO: document"""
    try:
        ids = []
        operator_in = {'$in': []}
        filter_public_ids = {'public_id': {}}
        for v in public_ids.split(","):
            try:
                ids.append(int(v))
            except (ValueError, TypeError):
                return abort(400)
        operator_in.update({'$in': ids})
        filter_public_ids.update({'public_id': operator_in})

        ack = []
        objects = object_manager.get_objects_by(**filter_public_ids)

        # At the current state it is not possible to bulk delete objects with locations
        # check if any object has a location
        for current_object_instance in objects:
            try:
                location_for_object = locations_manager.get_location_for_object(current_object_instance.public_id)

                if location_for_object:
                    return ErrorBody(405, """It is not possible to bulk delete objects
                                             if any of them has a location""").response()
            except ManagerGetError:
                pass

        for current_object_instance in objects:
            try:
                # Remove object links and references
                delete_object_links(current_object_instance.public_id)
                manager.delete_all_object_references(current_object_instance.public_id)

                current_type_instance = object_manager.get_type(current_object_instance.get_type_id())
                current_object_render_result = CmdbRender(object_instance=current_object_instance,
                                                          object_manager=object_manager,
                                                          type_instance=current_type_instance,
                                                          render_user=request_user).result()
            except ObjectManagerGetError as err:
                LOGGER.error(err)
                return abort(404)
            except RenderError as err:
                LOGGER.error(err)
                return abort(500)

            try:
                ack.append(object_manager.delete_object(public_id=current_object_instance.get_public_id(),
                                                        user=request_user,
                                                        permission=AccessControlPermission.DELETE))
            except ObjectDeleteError:
                return abort(400)
            except AccessDeniedError as err:
                return abort(403, err.message)
            except CMDBError:
                return abort(500)

            try:
                # generate log
                log_data = {
                    'object_id': current_object_instance.get_public_id(),
                    'version': current_object_render_result.object_information['version'],
                    'user_id': request_user.get_public_id(),
                    'user_name': request_user.get_display_name(),
                    'comment': 'Object was deleted',
                    'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8')
                }
                logs_manager.insert_log(action=LogAction.DELETE, log_type=CmdbObjectLog.__name__, **log_data)
            except ManagerInsertError as err:
                LOGGER.error("ManagerInsertError: %s", err)

        return make_response({'successfully': ack})

    except ObjectDeleteError as error:
        return jsonify(message='Delete Error', error=error.message)
    except CMDBError:
        return abort(500)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   HELPER - METHODS                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def _fetch_only_active_objs() -> bool:
    """
    Checking if request have cookie parameter for object active state
    Returns:
        True if cookie is set or value is true else false
    """
    if request.args.get('onlyActiveObjCookie') is not None:
        value = request.args.get('onlyActiveObjCookie')
        return value in ['True', 'true']
            
    return False


def delete_object_links(public_id: int) -> None:
    """
    Deletes all object links where this public_id is set

    Args:
        public_id (int): public_id of the object which is deleted
    """
    object_link_filter: dict = {'$or': [{'primary': public_id}, {'secondary': public_id}]}

    builder_params = BuilderParameters(object_link_filter)

    links: list[ObjectLinkModel] = object_links_manager.iterate(builder_params).results

    for link in links:
        object_links_manager.delete({'public_id':link.public_id})
