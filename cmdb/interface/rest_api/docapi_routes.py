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
"""TODO: document"""
import logging
import json

from flask import abort, request, current_app, Response

from cmdb.framework.cmdb_object_manager import CmdbObjectManager
from cmdb.framework.results import IterationResult
from cmdb.interface.api_parameters import CollectionParameters
from cmdb.interface.response import GetMultiResponse
from cmdb.manager import ManagerIterationError, ManagerGetError
from cmdb.utils.error import CMDBError
from cmdb.interface.route_utils import make_response, login_required, insert_request_user, right_required
from cmdb.interface.blueprint import RootBlueprint, APIBlueprint
from cmdb.docapi.docapi_base import DocApiManager
from cmdb.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.docapi.docapi_template.docapi_template_manager import DocapiTemplateManagerGetError, \
    DocapiTemplateManagerInsertError, DocapiTemplateManagerUpdateError, DocapiTemplateManagerDeleteError, \
    DocapiTemplateManager
from cmdb.user_management import UserModel
# -------------------------------------------------------------------------------------------------------------------- #
with current_app.app_context():
    docapi_tpl_manager = DocapiTemplateManager(current_app.database_manager, current_app.event_queue)
    object_manager = CmdbObjectManager(current_app.database_manager, current_app.event_queue)

LOGGER = logging.getLogger(__name__)

docapi_blueprint = RootBlueprint('docapi', __name__, url_prefix='/docapi')
docs_blueprint = APIBlueprint('docs', __name__)


# DEFAULT ROUTES
@docs_blueprint.route('/template', methods=['GET', 'HEAD'])
@docs_blueprint.protect(auth=True, right='base.docapi.template.view')
@docs_blueprint.parse_collection_parameters()
def get_template_list(params: CollectionParameters):
    """TODO: document"""
    template_manager = DocapiTemplateManager(database_manager=current_app.database_manager)
    body = request.method == 'HEAD'

    try:
        iteration_result: IterationResult[DocapiTemplate] = template_manager.get_templates(
            filter=params.filter, limit=params.limit, skip=params.skip, sort=params.sort, order=params.order)
        types = [DocapiTemplate.to_json(type) for type in iteration_result.results]
        api_response = GetMultiResponse(types, total=iteration_result.total, params=params,
                                        url=request.url, model=DocapiTemplate.MODEL, body=body)
    except ManagerIterationError as err:
        return abort(400, err)
    except ManagerGetError as err:
        return abort(404, err)
    return api_response.make_response()


@docapi_blueprint.route('/template/by/<string:searchfilter>/', methods=['GET'])
@docapi_blueprint.route('/template/by/<string:searchfilter>', methods=['GET'])
@login_required
@insert_request_user
@right_required('base.docapi.template.view')
def get_template_list_filtered(searchfilter: str, request_user: UserModel):
    """TODO: document"""
    try:
        filterdict = json.loads(searchfilter)
        tpl = docapi_tpl_manager.get_templates_by(**filterdict)
    except DocapiTemplateManagerGetError as err:
        return abort(404, err.message)
    return make_response(tpl)


@docapi_blueprint.route('/template/<int:public_id>/', methods=['GET'])
@docapi_blueprint.route('/template/<int:public_id>', methods=['GET'])
@login_required
@insert_request_user
@right_required('base.docapi.template.view')
def get_template(public_id, request_user: UserModel):
    """
        get template in database
        Returns:
            docapi template
        """
    try:
        tpl = docapi_tpl_manager.get_template(public_id)
    except DocapiTemplateManagerGetError as err:
        LOGGER.error(err)
        return abort(404)
    resp = make_response(tpl)
    return resp


@docapi_blueprint.route('/template/name/<string:name>/', methods=['GET'])
@docapi_blueprint.route('/template/name/<string:name>', methods=['GET'])
@login_required
@insert_request_user
@right_required('base.docapi.template.view')
def get_template_by_name(name: str, request_user: UserModel):
    """TODO: document"""
    try:
        tpl = docapi_tpl_manager.get_template_by_name(name=name)
    except DocapiTemplateManagerGetError as err:
        return abort(404, err.message)
    return make_response(tpl)


@docapi_blueprint.route('/template', methods=['POST'])
@docapi_blueprint.route('/template/', methods=['POST'])
@login_required
@insert_request_user
@right_required('base.docapi.template.add')
def add_template(request_user: UserModel):
    """TODO: document"""
    from bson import json_util
    add_data_dump = json.dumps(request.json)
    try:
        new_tpl_data = json.loads(add_data_dump, object_hook=json_util.object_hook)
        new_tpl_data['public_id'] = docapi_tpl_manager.get_new_id()
        new_tpl_data['author_id'] = request_user.get_public_id()
    except TypeError as err:
        LOGGER.warning(err)
        abort(400)
    try:
        template_instance = DocapiTemplate(**new_tpl_data)
    except CMDBError as err:
        LOGGER.debug(err)
        return abort(400)
    try:
        ack = docapi_tpl_manager.insert_template(template_instance)
    except DocapiTemplateManagerInsertError:
        return abort(500)

    resp = make_response(ack)
    return resp


@docapi_blueprint.route('/template', methods=['PUT'])
@docapi_blueprint.route('/template/', methods=['PUT'])
@login_required
@insert_request_user
@right_required('base.docapi.template.edit')
def update_template(request_user: UserModel):
    """TODO: document"""
    from bson import json_util
    add_data_dump = json.dumps(request.json)
    new_tpl_data = None
    try:
        new_tpl_data = json.loads(add_data_dump, object_hook=json_util.object_hook)
    except TypeError as err:
        LOGGER.warning(err)
        abort(400)
    try:
        update_tpl_instance = DocapiTemplate(**new_tpl_data)
    except CMDBError:
        return abort(400)
    try:
        docapi_tpl_manager.update_template(update_tpl_instance, request_user)
    except DocapiTemplateManagerUpdateError:
        return abort(500)
    resp = make_response(update_tpl_instance)
    return resp


@docapi_blueprint.route('/template/<int:public_id>/', methods=['DELETE'])
@docapi_blueprint.route('/template/<int:public_id>', methods=['DELETE'])
@login_required
@insert_request_user
@right_required('base.docapi.template.delete')
def delete_template(public_id: int, request_user: UserModel):
    """TODO: document"""
    try:
        ack = docapi_tpl_manager.delete_template(public_id=public_id, request_user=request_user)
    except DocapiTemplateManagerDeleteError:
        return abort(400)
    resp = make_response(ack)
    return resp


@docapi_blueprint.route('/template/<int:public_id>/render/<int:object_id>/', methods=['GET'])
@docapi_blueprint.route('/template/<int:public_id>/render/<int:object_id>', methods=['GET'])
@login_required
@insert_request_user
@right_required('base.framework.object.view')
def render_object_template(public_id: int, object_id: int, request_user: UserModel):
    """TODO: document"""
    docapi_manager = DocApiManager(docapi_tpl_manager, object_manager)
    output = docapi_manager.render_object_template(public_id, object_id)

    # Todo: error handling

    # return data
    return Response(
        output,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=output.pdf"
        }
    )
