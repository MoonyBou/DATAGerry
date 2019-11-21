# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2019 NETHINKS GmbH
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
This manager represents the core functionalities for the use of CMDB objects.
All communication with the objects is controlled by this manager.
The implementation of the manager used is always realized using the respective superclass.

"""
import logging
import re

from datetime import datetime
from typing import List

from cmdb.data_storage.database_manager import InsertError, PublicIDAlreadyExists
from cmdb.event_management.event import Event
from cmdb.framework.cmdb_base import CmdbManagerBase
from cmdb.framework.cmdb_category import CmdbCategory
from cmdb.framework.cmdb_collection import CmdbCollection, CmdbCollectionTemplate
from cmdb.framework.cmdb_errors import WrongInputFormatError, UpdateError, TypeInsertError, TypeAlreadyExists, \
    TypeNotFoundError, ObjectInsertError, ObjectDeleteError, NoRootCategories, ObjectManagerGetError, \
    ObjectManagerInsertError, ObjectManagerUpdateError
from cmdb.framework.cmdb_link import CmdbLink
from cmdb.framework.cmdb_object import CmdbObject
from cmdb.framework.cmdb_status import CmdbStatus
from cmdb.framework.cmdb_type import CmdbType
from cmdb.utils.error import CMDBError

LOGGER = logging.getLogger(__name__)


class CmdbObjectManager(CmdbManagerBase):
    def __init__(self, database_manager=None, event_queue=None):
        self._event_queue = event_queue
        super(CmdbObjectManager, self).__init__(database_manager)

    def is_ready(self) -> bool:
        return self.dbm.status()

    def get_new_id(self, collection: str) -> int:
        return self.dbm.get_next_public_id(collection)

    def get_object(self, public_id: int):
        try:
            return CmdbObject(
                **self._get(
                    collection=CmdbObject.COLLECTION,
                    public_id=public_id
                )
            )
        except (CMDBError, Exception) as err:
            raise ObjectManagerGetError(err.message)

    def get_objects(self, public_ids: list):
        object_list = []
        for public_id in public_ids:
            object_list.append(self.get_object(public_id))
        return object_list

    def get_objects_by(self, sort='public_id', **requirements):
        ack = []
        objects = self._get_many(collection=CmdbObject.COLLECTION, sort=sort, **requirements)
        for obj in objects:
            ack.append(CmdbObject(**obj))
        return ack

    def get_all_objects(self):
        ack = []
        objects = self._get_many(collection=CmdbObject.COLLECTION, sort='public_id')
        for obj in objects:
            ack.append(CmdbObject(**obj))
        return ack

    def get_objects_by_type(self, type_id: int):
        return self.get_objects_by(type_id=type_id)

    def count_objects_by_type(self, public_id: int):
        """This method does not actually
               performs the find() operation
               but instead returns
               a numerical count of the documents that meet the selection criteria.

               Args:
                   collection (str): name of database collection
                   public_id (int): public id of document
                   *args: arguments for search operation
                   **kwargs:

               Returns:
                   returns the count of the documents
               """

        formatted_type_id = {'type_id': public_id}
        return self.dbm.count(CmdbObject.COLLECTION, formatted_type_id)

    def count_objects(self):
        return self.dbm.count(collection=CmdbObject.COLLECTION)

    def _find_query_fields(self, query, match_fields=list()):
        for key, items in query.items():
            if isinstance(items, dict):
                if 'fields.value' == key:
                    match_fields.append(items['$regex'])
                else:
                    for item in items:
                        self._find_query_fields(item, match_fields=match_fields)
        return match_fields

    def _re_search_fields(self, search_object, regex):
        """returns list of matched fields"""
        match_list = list()
        for index in regex:
            for field in search_object.fields:
                if re.search(index, str(field['value'])):
                    match_list.append(field['name'])
        return match_list

    def search_objects(self, query: dict) -> dict:
        return self.search_objects_with_limit(query, limit=0)

    def search_objects_with_limit(self, query: dict, limit=0) -> dict:
        result_list = dict()
        for result_objects in self._search(CmdbObject.COLLECTION, query, limit=limit):
            try:
                re_query = self._find_query_fields(query)
                result_object_instance = CmdbObject(**result_objects)
                matched_fields = self._re_search_fields(result_object_instance, re_query)

                result_list.update({
                    result_object_instance: matched_fields
                })
            except (CMDBError, re.error):
                continue
        return result_list

    def insert_object(self, data: (CmdbObject, dict)) -> int:
        """
        Insert new CMDB Object
        Args:
            data: init data

        Returns:
            Public ID of the new object in database
        """
        if isinstance(data, dict):
            try:
                new_object = CmdbObject(**data)
            except CMDBError as e:
                LOGGER.debug(f'Error while inserting object - error: {e.message}')
                raise ObjectManagerInsertError(e)
        elif isinstance(data, CmdbObject):
            new_object = data
        try:
            ack = self.dbm.insert(
                collection=CmdbObject.COLLECTION,
                data=new_object.to_database()
            )
            if self._event_queue:
                event = Event("cmdb.core.object.added", {"id": new_object.get_public_id(),
                                                         "type_id": new_object.get_type_id()})
                self._event_queue.put(event)
        except (CMDBError, PublicIDAlreadyExists) as e:
            raise ObjectInsertError(e)
        return ack

    def insert_many_objects(self, objects: list):
        ack = []
        for obj in objects:
            if isinstance(obj, CmdbObject):
                ack.append(self.insert_object(obj.to_database()))
            elif isinstance(obj, dict):
                ack.append(self.insert_object(obj))
            else:
                raise Exception
        return ack

    def update_object(self, data: (dict, CmdbObject)) -> str:
        if isinstance(data, dict):
            update_object = CmdbObject(**data)
        elif isinstance(data, CmdbObject):
            update_object = data
        else:
            raise ObjectManagerUpdateError('Wrong CmdbObject init format - expecting CmdbObject or dict')
        update_object.last_edit_time = datetime.utcnow()
        ack = self.dbm.update(
            collection=CmdbObject.COLLECTION,
            public_id=update_object.get_public_id(),
            data=update_object.to_database()
        )
        # create cmdb.core.object.updated event
        if self._event_queue:
            event = Event("cmdb.core.object.updated", {"id": update_object.get_public_id(),
                                                       "type_id": update_object.get_type_id()})
            self._event_queue.put(event)
        return ack.acknowledged

    def update_many_objects(self, objects: list):
        ack = []
        for obj in objects:
            if isinstance(obj, CmdbObject):
                ack.append(self.update_object(obj.to_database()))
            elif isinstance(obj, dict):
                ack.append(self.update_object(obj))
            else:
                raise Exception
        return ack

    def remove_object_fields(self, filter_query: dict, update: dict):
        ack = self._update_many(CmdbObject.COLLECTION, filter_query, update)
        return ack

    def update_object_fields(self, filter: dict, update: dict):
        ack = self._update_many(CmdbObject.COLLECTION, filter, update)
        return ack

    def get_object_references(self, public_id: int) -> list:
        # Type of given object id
        type_id = self.get_object(public_id=public_id).get_type_id()

        # query for all types with ref input type with value of type id
        req_type_query = {"fields": {"$elemMatch": {"type": "ref", "$and": [{"ref_types": int(type_id)}]}}}

        # get type list with given query
        req_type_list = self.get_types_by(**req_type_query)

        type_init_list = []
        for new_type_init in req_type_list:
            try:
                current_loop_type = new_type_init
                ref_field = current_loop_type.get_field_of_type_with_value(input_type='ref', _filter='ref_types',
                                                                           value=type_id)
                type_init_list.append(
                    {"type_id": current_loop_type.get_public_id(), "field_name": ref_field['name']})
            except CMDBError as e:
                LOGGER.warning('Unsolvable type reference with type {}'.format(e.message))
                continue

        referenced_by_objects = []
        for possible_object_types in type_init_list:
            referenced_query = {"type_id": possible_object_types['type_id'], "fields": {
                "$elemMatch": {"$and": [{"name": possible_object_types['field_name']}],
                               "$or": [{"value": int(public_id)}, {"value": str(public_id)}]}}}
            referenced_by_objects = referenced_by_objects + self.get_objects_by(**referenced_query)

        return referenced_by_objects

    def delete_object(self, public_id: int):
        try:
            ack = self._delete(CmdbObject.COLLECTION, public_id)
            if self._event_queue:
                event = Event("cmdb.core.object.deleted", {"id": public_id})
                self._event_queue.put(event)
            return ack
        except (CMDBError, Exception):
            raise ObjectDeleteError(obj_id=public_id)

    def delete_many_objects(self, filter_query: dict, public_ids):
        ack = self._delete_many(CmdbObject.COLLECTION, filter_query)
        if self._event_queue:
            event = Event("cmdb.core.objects.deleted", {"ids": public_ids})
            self._event_queue.put(event)
        return ack

    def get_all_types(self):
        ack = []
        types = self._get_many(collection=CmdbType.COLLECTION)
        for type_obj in types:
            ack.append(CmdbType(**type_obj))
        return ack

    def get_type(self, public_id: int):
        try:
            return CmdbType(**self.dbm.find_one(
                collection=CmdbType.COLLECTION,
                public_id=public_id)
                            )
        except (CMDBError, Exception) as e:
            raise ObjectManagerGetError(err=e)

    def get_type_by(self, **requirements) -> CmdbType:
        try:
            found_type_list = self._get_many(collection=CmdbType.COLLECTION, limit=1, **requirements)
            if len(found_type_list) > 0:
                return CmdbType(**found_type_list[0])
            else:
                raise ObjectManagerGetError(err='More than 1 type matches this requirement')
        except (CMDBError, Exception) as e:
            raise ObjectManagerGetError(err=e)

    def get_types_by(self, sort='public_id', **requirements):
        ack = []
        objects = self._get_many(collection=CmdbType.COLLECTION, sort=sort, **requirements)
        for data in objects:
            ack.append(CmdbType(**data))
        return ack

    def insert_type(self, data: (CmdbType, dict)):
        if isinstance(data, CmdbType):
            new_type = data
        elif isinstance(data, dict):
            new_type = CmdbType(**data)
        else:
            raise WrongInputFormatError(CmdbType, data, "Possible data: dict or CmdbType")
        try:
            ack = self._insert(collection=CmdbType.COLLECTION, data=new_type.to_database())
            LOGGER.debug(f"Inserted new type with ack {ack}")
            if self._event_queue:
                event = Event("cmdb.core.objecttype.added", {"id": new_type.get_public_id()})
                self._event_queue.put(event)
        except PublicIDAlreadyExists:
            raise TypeAlreadyExists(type_id=new_type.get_public_id())
        except (CMDBError, InsertError):
            raise TypeInsertError(new_type.get_public_id())
        return ack

    def update_type(self, data: (CmdbType, dict)):
        if isinstance(data, CmdbType):
            update_type = data
        elif isinstance(data, dict):
            update_type = CmdbType(**data)
        else:
            raise WrongInputFormatError(CmdbType, data, "Possible data: dict or CmdbType")

        ack = self._update(
            collection=CmdbType.COLLECTION,
            public_id=update_type.get_public_id(),
            data=update_type.to_database()
        )
        if self._event_queue:
            event = Event("cmdb.core.objecttype.updated", {"id": update_type.get_public_id()})
            self._event_queue.put(event)
        return ack

    def update_many_types(self, filter: dict, update: dict):
        ack = self._update_many(CmdbType.COLLECTION, filter, update)
        return ack

    def count_types(self):
        return self.dbm.count(collection=CmdbType.COLLECTION)

    def delete_type(self, public_id: int):
        ack = self._delete(CmdbType.COLLECTION, public_id)
        if self._event_queue:
            event = Event("cmdb.core.objecttype.deleted", {"id": public_id})
            self._event_queue.put(event)
        return ack

    def delete_many_types(self, filter_query: dict, public_ids):
        ack = self._delete_many(CmdbType.COLLECTION, filter_query)
        if self._event_queue:
            event = Event("cmdb.core.objecttypes.deleted", {"ids": public_ids})
            self._event_queue.put(event)
        return ack

    def get_all_categories(self):
        ack = []
        cats = self.dbm.find_all(collection=CmdbCategory.COLLECTION, sort=[('public_id', 1)])
        for cat_obj in cats:
            try:
                ack.append(CmdbCategory(**cat_obj))
            except CMDBError as e:
                LOGGER.debug("Error while parsing Category")
                LOGGER.debug(e.message)
        return ack

    def get_categories_by(self, _filter: dict) -> list:
        """
        get all categories by requirements
        """
        ack = []
        query_filter = _filter
        root_categories = self.dbm.find_all(collection=CmdbCategory.COLLECTION, filter=query_filter)
        for cat_obj in root_categories:
            try:
                ack.append(CmdbCategory(**cat_obj))
            except CMDBError as e:
                LOGGER.debug("Error while parsing Category")
                LOGGER.debug(e.message)
        return ack

    def _get_category_nodes(self, parent_list: list) -> dict:
        edge = []
        for cat_child in parent_list:
            next_children = self.get_categories_by(_filter={'parent_id': cat_child.get_public_id()})
            if len(next_children) > 0:
                edge.append({
                    'category': cat_child,
                    'children': self._get_category_nodes(next_children)
                })
            else:
                edge.append({
                    'category': cat_child,
                    'children': None
                })
        return edge

    def get_category_tree(self) -> dict:
        tree = list()
        root_categories = self.get_categories_by(_filter={
            '$or': [
                {'parent_id': {'$exists': False}},
                {'parent_id': 0}
            ]
        })
        if len(root_categories) > 0:
            tree = self._get_category_nodes(root_categories)
        else:
            raise NoRootCategories()
        return tree

    def get_category(self, public_id: int):
        return CmdbCategory(**self.dbm.find_one(
            collection=CmdbCategory.COLLECTION,
            public_id=public_id)
                            )

    def insert_category(self, data: (CmdbCategory, dict)):
        if isinstance(data, CmdbCategory):
            new_category = data
        elif isinstance(data, dict):
            new_category = CmdbCategory(**data)

        return self._insert(collection=CmdbCategory.COLLECTION, data=new_category.to_database())

    def update_category(self, data: dict):
        if isinstance(data, CmdbCategory):
            update_category = data
        elif isinstance(data, dict):
            update_category = CmdbCategory(**data)
        ack = self.dbm.update(
            collection=CmdbCategory.COLLECTION,
            public_id=update_category.get_public_id() or update_category.public_id,
            data=update_category.to_database()
        )
        return ack

    def delete_category(self, public_id: int):
        ack = self._delete(CmdbCategory.COLLECTION, public_id)
        return ack

    # STATUS CRUD
    def get_statuses(self) -> list:
        status_list = list()
        try:
            collection_resp = self.dbm.find_all(collection=CmdbStatus.COLLECTION)
        except(CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

        for collection in collection_resp:
            try:
                status_list.append(CmdbStatus(
                    **collection
                ))
            except(CMDBError, Exception) as err:
                LOGGER.error(err)
                continue
        return status_list

    def get_status(self, public_id) -> CmdbStatus:
        try:
            return CmdbStatus(**self.dbm.find_one(
                collection=CmdbStatus.COLLECTION,
                public_id=public_id
            ))
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

    def insert_status(self, data) -> int:
        try:
            new_status = CmdbStatus(**data)
            ack = self.dbm.insert(CmdbStatus.COLLECTION, new_status.to_database())
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerInsertError(err)
        return ack

    def update_status(self, data):
        try:
            updated_status = CmdbStatus(**data)
            ack = self.dbm.update(CmdbStatus.COLLECTION, updated_status.get_public_id(), updated_status.to_database())
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerUpdateError(err)
        return ack.acknowledged

    def delete_status(self, public_id: int):
        return NotImplementedError

    # COLLECTIONS/TEMPLATES CRUD
    def get_collections(self) -> list:
        collection_list = list()
        try:
            collection_resp = self.dbm.find_all(collection=CmdbCollection.COLLECTION)
        except(CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

        for collection in collection_resp:
            try:
                collection_list.append(CmdbCollection(
                    **collection
                ))
            except(CMDBError, Exception) as err:
                LOGGER.error(err)
                continue
        return collection_list

    def get_collection(self, public_id: int) -> CmdbCollection:
        try:
            return CmdbCollection(**self.dbm.find_one(
                collection=CmdbCollection.COLLECTION,
                public_id=public_id
            ))
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

    def insert_collection(self, data) -> int:
        try:
            new_collection = CmdbCollection(**data)
            ack = self.dbm.insert(CmdbCollection.COLLECTION, new_collection.to_database())
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerInsertError(err)
        return ack

    def update_collection(self, data):
        return NotImplementedError

    def delete_collection(self, public_id: int):
        return NotImplementedError

    def get_collection_templates(self) -> list:
        collection_template_list = list()
        try:
            collection_resp = self.dbm.find_all(collection=CmdbCollectionTemplate.COLLECTION)
        except(CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

        for collection in collection_resp:
            try:
                collection_template_list.append(CmdbCollectionTemplate(
                    **collection
                ))
            except(CMDBError, Exception) as err:
                LOGGER.error(err)
                continue
        return collection_template_list

    def get_collection_template(self, public_id: int) -> CmdbCollectionTemplate:
        try:
            return CmdbCollectionTemplate(**self.dbm.find_one(
                collection=CmdbCollectionTemplate.COLLECTION,
                public_id=public_id
            ))
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerGetError(err)

    def insert_collection_template(self, data) -> int:
        try:
            new_collection_template = CmdbCollectionTemplate(**data)
            ack = self.dbm.insert(CmdbCollectionTemplate.COLLECTION, new_collection_template.to_database())
        except (CMDBError, Exception) as err:
            LOGGER.error(err)
            raise ObjectManagerInsertError(err)
        return ack

    def update_collection_template(self, data):
        return NotImplementedError

    def delete_collection_template(self, public_id: int):
        return NotImplementedError

    # Link CRUD
    def get_link(self, public_id: int):
        try:
            return CmdbLink(**self._get(collection=CmdbLink.COLLECTION, public_id=public_id))
        except (CMDBError, Exception) as err:
            raise ObjectManagerGetError(err)

    def get_links_by_partner(self, public_id: int) -> List[CmdbLink]:
        query = {
            '$or': [
                {'primary': public_id},
                {'secondary': public_id}
            ]
        }
        link_list: List[CmdbLink] = []
        try:
            find_list: List[dict] = self._get_many(CmdbLink.COLLECTION, **query)
            LOGGER.debug(find_list)
            for link in find_list:
                link_list.append(CmdbLink(**link))
        except CMDBError as err:
            raise ObjectManagerGetError(err)
        return link_list

    def insert_link(self, data: dict):
        try:
            new_link = CmdbLink(public_id=self.get_new_id(collection=CmdbLink.COLLECTION), **data)
            return self._insert(CmdbLink.COLLECTION, new_link.to_database())
        except (CMDBError, Exception) as err:
            raise ObjectManagerInsertError(err)
