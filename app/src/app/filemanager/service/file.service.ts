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

import { Injectable } from '@angular/core';
import { Observable, timer } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import {
  ApiCallService,
  ApiService,
  httpFileOptions, httpObserveOptions,
} from '../../services/api-call.service';
import { HttpParams, HttpResponse} from '@angular/common/http';
import { ValidatorService } from '../../services/validator.service';
import { FileMetadata } from '../model/metadata';
import { FormControl } from '@angular/forms';
import { FileElement } from '../model/file-element';

export const checkFolderExistsValidator = (fileService: FileService, metadata: any, time: number = 500) => {
  return (control: FormControl) => {
    return timer(time).pipe(switchMap(() => {
      return fileService.getFileElement(control.value, metadata).pipe(
        map((apiResponse: HttpResponse<any[]>) => {
          return apiResponse.body ? { folderExists: true } : null;
        }),
        catchError(() => {
          return new Promise(resolve => {
            resolve(null);
          });
        })
      );
    }));
  };
};

export const PARAMETER = 'params';

@Injectable({
  providedIn: 'root'
})

export class FileService<T = any> implements ApiService {
  public servicePrefix: string = 'media_file';

  constructor(private api: ApiCallService) {
  }

  /**
   * Get all files as a list
   */
  public getAllFilesList(metadata: FileMetadata, ...options): Observable<T[]> {

    let params: HttpParams = new HttpParams();
    for (const option of options) {
      for (const key of Object.keys(option)) {
        params = params.append(key, option[key]);
      }
    }
    params = params.append('metadata', JSON.stringify(metadata));
    httpObserveOptions[PARAMETER] = params;
    return this.api.callGet<T[]>(this.servicePrefix + '/', httpObserveOptions).pipe(
      map((apiResponse: HttpResponse<T[]>) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }

  /**
   * Add a new file into the database (GridFS)
   * @param file raw instance
   * @param metadata raw instance
   */
  public postFile(file: File, metadata: FileMetadata): Observable<T> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('metadata', JSON.stringify(metadata));
    httpFileOptions.responseType = 'json';
    return this.api.callPost<any>(`${ this.servicePrefix }/`, formData, httpFileOptions).pipe(
      map((apiResponse: HttpResponse<any>) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body.raw;
      })
    );
  }

  /**
   * Update file into the database (GridFS)
   * @param file raw instance
   */
  public putFile(file: FileElement): Observable<T> {
    return this.api.callPut<number>(this.servicePrefix + '/', JSON.stringify(file)).pipe(
      map((apiResponse: HttpResponse<T>) => {
        return apiResponse.body;
      })
    );
  }


  /**
   * Download a file by name
   * @param filename name of the file
   * @param metadata raw instance
   */
  public downloadFile(filename: string, metadata) {
    const formData = new FormData();
    formData.append('metadata', JSON.stringify(metadata));
    return this.api.callPost(this.servicePrefix + '/download/' + filename, formData, httpFileOptions);
  }

  /**
   * Get a list of files by a regex requirement
   * Works with name
   * @param regex parameter
   */
  public getFilesListByRegex(regex: string): Observable<T[]> {
    regex = ValidatorService.validateRegex(regex).trim();
    return this.api.callGet<T[]>(this.servicePrefix + '/download/' + encodeURIComponent(regex)).pipe(
      map((apiResponse: HttpResponse<T[]>) => {
        if (apiResponse.status === 204) {
          return [];
        }
        return apiResponse.body;
      })
    );
  }


  /**
   * Delete a existing files
   * @param fileID the file id
   * @param params metadata raw instance
   */
  public deleteFile(fileID: number, params): Observable<any> {
    httpFileOptions[PARAMETER] = {metadata : JSON.stringify(params)};
    return this.api.callDelete<any>(this.servicePrefix + '/' + fileID, httpFileOptions).pipe(
      map((apiResponse: HttpResponse<any>) => {
        return apiResponse.body;
      })
    );
  }

  /**
   * Validation: Check folder name for uniqueness
   *  @param filename must be unique
   *  @param metadata raw instance
   */
  public getFileElement(filename: string, metadata: FileMetadata) {
    httpObserveOptions[PARAMETER] = {metadata : JSON.stringify(metadata)};
    return this.api.callGet<T>(`${ this.servicePrefix }/${ filename }`, httpObserveOptions);
  }

  /**
   * This function provides building  file and directory paths.
   * @param publicID from the selected file
   * @param path separator
   * @param tree of all folder files
   */
  public pathBuilder(publicID: number, path: string[], tree: FileElement[]) {
    const temp = tree.find(f => f.public_id === publicID);
    const checker = temp ? temp.name : '';
    path.push(checker);
    if (temp && temp.metadata && temp.metadata.parent) {
      return this.pathBuilder(temp.metadata.parent, path, tree);
    }
    return path.reverse();
  }
}
