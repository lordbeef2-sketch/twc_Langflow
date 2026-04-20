import { cloneDeep } from "lodash";
import { useRef } from "react";
import buildQueryStringUrl from "@/controllers/utils/create-query-param-string";
import type { PaginatedFolderType } from "@/pages/MainPage/entities";
import { useFolderStore } from "@/stores/foldersStore";
import type { useQueryFunctionType } from "@/types/api";
import type { FlowType } from "@/types/flow";
import { processFlows } from "@/utils/reactflowUtils";
import {
  SHARED_WITH_ME_FOLDER_DESCRIPTION,
  SHARED_WITH_ME_FOLDER_ID,
  SHARED_WITH_ME_FOLDER_NAME,
} from "@/utils/flowAccess";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface IGetFolder {
  id: string;
  page?: number;
  size?: number;
  is_component?: boolean;
  is_flow?: boolean;
  search?: string;
}

const addQueryParams = (url: string, params: IGetFolder): string => {
  return buildQueryStringUrl(url, params);
};

export const useGetFolderQuery: useQueryFunctionType<
  IGetFolder,
  PaginatedFolderType | undefined
> = (params, options) => {
  const { query } = UseRequestProcessor();

  const folders = useFolderStore((state) => state.folders);
  const latestIdRef = useRef("");

  const getFolderFn = async (
    params: IGetFolder,
  ): Promise<PaginatedFolderType | undefined> => {
    if (params.id === SHARED_WITH_ME_FOLDER_ID) {
      const queryString = new URLSearchParams({
        ...(params.is_component ? { is_component: "true" } : {}),
        ...(params.is_flow ? { is_flow: "true" } : {}),
        ...(params.search ? { search: params.search } : {}),
      });
      const { data } = await api.get<FlowType[]>(
        `${getURL("FLOWS")}/shared/accepted${queryString.toString() ? `?${queryString.toString()}` : ""}`,
      );
      const { flows } = processFlows(data);
      const page = params.page ?? 1;
      const size = params.size ?? 12;
      const startIndex = (page - 1) * size;
      const paginatedItems = flows.slice(startIndex, startIndex + size);
      const total = flows.length;

      return {
        folder: {
          id: SHARED_WITH_ME_FOLDER_ID,
          name: SHARED_WITH_ME_FOLDER_NAME,
          description: SHARED_WITH_ME_FOLDER_DESCRIPTION,
          parent_id: null,
          components: [],
          readonly: true,
          is_shared_folder: true,
        },
        flows: {
          items: paginatedItems,
          total,
          page,
          size,
          pages: Math.max(1, Math.ceil(total / size)),
        },
      };
    }

    if (params.id) {
      if (latestIdRef.current !== params.id) {
        params.page = 1;
      }
      latestIdRef.current = params.id;

      const existingFolder = folders.find((f) => f.id === params.id);
      if (!existingFolder) {
        return;
      }
    }

    const url = addQueryParams(`${getURL("PROJECTS")}/${params.id}`, params);
    const { data } = await api.get<PaginatedFolderType>(url);

    const { flows } = processFlows(data.flows.items);

    const dataProcessed = cloneDeep(data);
    dataProcessed.flows.items = flows;

    return dataProcessed;
  };

  const queryResult = query(
    [
      "useGetFolder",
      params.id,
      {
        page: params.page,
        size: params.size,
        is_component: params.is_component,
        is_flow: params.is_flow,
        search: params.search,
      },
    ],
    () => getFolderFn(params),
    {
      refetchOnWindowFocus: false,
      ...options,
    },
  );

  return queryResult;
};
