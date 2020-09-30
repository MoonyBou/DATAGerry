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
# along with this program. If not, see <https://www.gnu.org/licenses/>.
from typing import Union, List

from cmdb.data_storage.database_manager import DatabaseManagerMongo
from cmdb.user_management.models.user import UserModel
from .account_manager import AccountManager
from .. import UserGroupModel
from ...framework.results import IterationResult
from ...framework.utils import PublicID
from ...manager import ManagerGetError, ManagerIterationError, ManagerDeleteError
from ...search import Query


class UserManager(AccountManager):

    def __init__(self, database_manager: DatabaseManagerMongo):
        super(UserManager, self).__init__(UserModel.COLLECTION, database_manager=database_manager)

    def iterate(self, filter: dict, limit: int, skip: int, sort: str, order: int, *args, **kwargs) \
            -> IterationResult[UserModel]:
        """
        Iterate over a collection of user resources.

        Args:
            filter: match requirements of field values
            limit: max number of elements to return
            skip: number of elements to skip first
            sort: sort field
            order: sort order
            *args:
            **kwargs:

        Returns:
            IterationResult: Instance of IterationResult with generic UserModel.
        """
        try:
            query: Query = self.builder.build(filter=filter, limit=limit, skip=skip, sort=sort, order=order)
            aggregation_result = next(self._aggregate(self.collection, query))
        except ManagerGetError as err:
            raise ManagerIterationError(err=err)
        iteration_result: IterationResult[UserModel] = IterationResult.from_aggregation(aggregation_result)
        iteration_result.convert_to(UserModel)
        return iteration_result

    def get(self, public_id: Union[PublicID, int]) -> UserModel:
        """
        Get a single user by its id.

        Args:
            public_id (int): ID of the user.

        Returns:
            UserModel: Instance of UserModel with data.
        """
        result = self._get(self.collection, filter={'public_id': public_id}, limit=1)
        for resource_result in result.limit(-1):
            return UserModel.from_data(resource_result)
        raise ManagerGetError(f'User with ID: {public_id} not found!')

    def get_by(self, query: Query) -> UserModel:
        """
        Get a single user by a query.

        Args:
            query (Query): Query filter of user parameters.

        Returns:
            UserModel: Instance of UserModel with matching data.
        """
        result = self._get(self.collection, filter=query, limit=1)
        for resource_result in result.limit(-1):
            return UserModel.from_data(resource_result)
        raise ManagerGetError(f'User with the query: {query} not found!')

    def get_many(self, query: Query = None) -> List[UserModel]:
        """
        Get a collection of users by a query. Passing no query means all users.

        Args:
            query (Query): A database query for filtering.

        Returns:
            List[UserModel]: A list of all users which matches the query.
        """
        query = query or {}
        results = self._get(self.collection, filter=query)
        return [UserModel.from_data(user) for user in results]

    def insert(self, user: Union[UserModel, dict]) -> PublicID:
        """
        Insert a single user into the system.

        Args:
            user (dict): Raw data of the user.

        Notes:
            If no public id was given, the database manager will auto insert the next available ID.

        Returns:
            int: The Public ID of the new inserted user
        """
        if isinstance(user, UserModel):
            user = UserModel.to_data(user)
        return self._insert(self.collection, resource=user)

    def update(self, public_id: Union[PublicID, int], user: Union[UserModel, dict]):
        """
        Update a existing user in the system.

        Args:
            public_id (int): PublicID of the user in the system.
            user(UserModel): Instance or dict of UserModel

        Notes:
            If a UserModel instance was passed as user argument, \
            it will be auto converted via the model `to_json` method.
        """
        if isinstance(user, UserModel):
            user = UserModel.to_data(user)
        return self._update(public_id=public_id, filter={'public_id': public_id}, resource=user)

    def delete(self, public_id: Union[PublicID, int]) -> UserModel:
        """
        Delete a existing user by its PublicID.

        Args:
            public_id (int): PublicID of the user in the system.

        Raises:
            ManagerDeleteError: If you try to delete the admin \
                                or something happened during the database operation.

        Returns:
            UserModel: The deleted user as its model.
        """
        if public_id in [1]:
            raise ManagerDeleteError(f'You cant delete the admin user')
        user: UserModel = self.get(public_id=public_id)
        delete_result = self._delete(self.collection, public_id=public_id)

        if delete_result.deleted_count == 0:
            raise ManagerDeleteError(err='No user matched this public id')
        return user
