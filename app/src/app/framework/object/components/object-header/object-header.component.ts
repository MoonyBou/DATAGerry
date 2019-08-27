/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2019 NETHINKS GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, Input } from '@angular/core';
import { CmdbObject } from '../../../models/cmdb-object';
import { CmdbType } from '../../../models/cmdb-type';

@Component({
  selector: 'cmdb-object-header',
  templateUrl: './object-header.component.html',
  styleUrls: ['./object-header.component.scss']
})
export class ObjectHeaderComponent {

  @Input() public objectInstance: CmdbObject;
  @Input() public typeInstance: CmdbType;

}
