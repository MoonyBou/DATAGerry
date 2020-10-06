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

import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { User } from '../../models/user';
import { UserService } from '../../services/user.service';
import { GroupService } from '../../services/group.service';
import { Group } from '../../models/group';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
  selector: 'cmdb-user-view',
  templateUrl: './user-view.component.html',
  styleUrls: ['./user-view.component.scss']
})
export class UserViewComponent implements OnInit, OnDestroy {

  private unSubscriber: Subject<void>;

  public userID: number;
  public user: User;
  public group: Group;

  constructor(private route: ActivatedRoute, public userService: UserService, public groupService: GroupService) {
    this.unSubscriber = new Subject<void>();
    this.route.params.subscribe((id) => this.userID = id.publicID);
  }

  public ngOnInit(): void {
    this.userService.getUser(this.userID).pipe(takeUntil(this.unSubscriber)).subscribe((user: User) => {
      this.user = user;
      this.groupService.getGroup(this.user.group_id).pipe(takeUntil(this.unSubscriber))
        .subscribe((group: Group) => this.group = group);
    });
  }

  public ngOnDestroy(): void {
    this.unSubscriber.next();
    this.unSubscriber.complete();
  }

}
