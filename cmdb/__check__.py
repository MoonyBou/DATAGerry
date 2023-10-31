# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2023 becon GmbH
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
This module contains logics for database validation and setup
"""

import logging
from enum import Enum

from cmdb.framework.cmdb_location import CmdbLocation

LOGGER = logging.getLogger(__name__)


class CheckRoutine:
    """
    This class holds checks for the database check routines
    """

    class CheckStatus(Enum):
        """
        Enumeration of the status options for checks
        """
        NOT = 0
        RUNNING = 1
        HAS_UPDATES = 2
        FINISHED = 3


    def __init__(self, dbm):
        self.status: int = CheckRoutine.CheckStatus.NOT
        self.setup_database_manager = dbm


    def get_check_status(self) -> int:
        """
        Returns the CheckStatus of the current CheckRoutine

        Returns:
            (int): Current CheckStatus
        """
        return self.status

    def checker(self):
        LOGGER.info('CHECK ROUTINE: STARTED...')
        self.status = CheckRoutine.CheckStatus.FINISHED

        # check database
        if not self.__is_database_empty():
            if not (self.__check_database_collection_valid() and self.has_updates()):
                LOGGER.warning(
                    'The current database version does not match the valid database version.'
                )
                self.status = CheckRoutine.CheckStatus.HAS_UPDATES
        LOGGER.info('CHECK ROUTINE: FINISHED!')
        return self.status

    def __is_database_empty(self) -> bool:
        """
        Checks if there are any collections in the initialised database

        Returns:
            (bool): Returns bool if there are any collection in the initialised database
        """
        return not self.setup_database_manager.connector.database.list_collection_names()

    def __check_database_collection_valid(self) -> bool:
        LOGGER.info('CHECK ROUTINE: Checking database collection validation')
        from cmdb.framework import __COLLECTIONS__ as FRAMEWORK_CLASSES
        from cmdb.user_management import __COLLECTIONS__ as USER_MANAGEMENT_COLLECTION
        from cmdb.exportd import __COLLECTIONS__ as JOB_MANAGEMENT_COLLECTION
        detected_database = self.setup_database_manager.connector.database
        collection_test = True

        try:
            # framework collections
            for collection in FRAMEWORK_CLASSES:
                collection_test = detected_database.validate_collection(collection.COLLECTION, scandata=True)['valid']

                # setup locations if valid test
                if collection == CmdbLocation and collection_test:
                    root_location: CmdbLocation = self.setup_database_manager.find_one(collection.COLLECTION, 1)

                    if root_location:
                        if self.setup_database_manager.validate_root_location(CmdbLocation.to_data(root_location)):
                            LOGGER.info("CHECK ROUTINE: Root Location valid")
                        else:
                            LOGGER.info("CHECK ROUTINE: Root Location invalalid => Fixing the Issue!")
                            self.setup_database_manager.set_root_location(collection.COLLECTION, create=False)

                    else:
                        LOGGER.info("CHECK ROUTINE: No Root Location => Creating a new Root Location!")
                        self.setup_database_manager.set_root_location(collection.COLLECTION, create=True)
                        

            # user management collections
            for collection in USER_MANAGEMENT_COLLECTION:
                collection_test = detected_database.validate_collection(collection.COLLECTION, scandata=True)['valid']
            # exportdJob management collections
            for collection in JOB_MANAGEMENT_COLLECTION:
                collection_test = detected_database.validate_collection(collection.COLLECTION, scandata=True)[
                    'valid']
        except Exception as ex:
            LOGGER.info(f'CHECK ROUTINE: Database collection validation for "{collection.COLLECTION}" failed. '
                        f'msgerror: {ex}')
            collection_test = False

        LOGGER.info(f'CHECK ROUTINE: Database collection validation status {collection_test}')
        return collection_test

    def has_updates(self) -> bool:
        """
        Check if updates are available

        Returns:
            (bool): True if updates are available else raises an error
        """
        from cmdb.updater import UpdaterModule
        from cmdb.utils.system_reader import SystemSettingsReader, SectionError

        try:
            ssr = SystemSettingsReader(self.setup_database_manager)
            ssr.get_all_values_from_section('updater')

            upd_module = UpdaterModule(ssr)
            new_version = upd_module.get_last_version()['version']
            current_version = upd_module.settings.version

            if new_version > current_version:
                LOGGER.error(
                    f'Please run an update. There are new updates available.'
                    f'Current Updater Version: {current_version} '
                    f'Newest Update Version: {new_version}'
                )
                return False

        except SectionError as err:
            LOGGER.error(err.message)
            return False

        return True
    