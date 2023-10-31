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

from cmdb.user_management.models.right import BaseRight, Levels


class SystemRight(BaseRight):
    MIN_LEVEL = Levels.SECURE
    PREFIX = '{}.{}'.format(BaseRight.PREFIX, 'system')

    def __init__(self, name: str, level: Levels = Levels.SECURE, description: str = None):
        super(SystemRight, self).__init__(level, name, description=description)


