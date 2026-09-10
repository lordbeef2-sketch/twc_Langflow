import type { FolderType } from "@/pages/MainPage/entities";
import useAuthStore from "@/stores/authStore";
import { useFolderStore } from "@/stores/foldersStore";
import { useUtilityStore } from "@/stores/utilityStore";
import type { useQueryFunctionType } from "@/types/api";
import {
  SHARED_WITH_ME_FOLDER_DESCRIPTION,
  SHARED_WITH_ME_FOLDER_ID,
  SHARED_WITH_ME_FOLDER_NAME,
} from "@/utils/flowAccess";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetFoldersQuery: useQueryFunctionType<
  undefined,
  FolderType[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const setMyCollectionId = useFolderStore((state) => state.setMyCollectionId);
  const setFolders = useFolderStore((state) => state.setFolders);
  const defaultFolderName = useUtilityStore((state) => state.defaultFolderName);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  const getFoldersFn = async (): Promise<FolderType[]> => {
    const res = await api.get(`${getURL("PROJECTS")}/`);
    const data = res.data as FolderType[];

    // Find default folder by name, or fall back to first folder if not found
    const myCollectionId =
      data?.find((f) => f.name === defaultFolderName)?.id ?? data?.[0]?.id;
    const sharedFolder: FolderType = {
      id: SHARED_WITH_ME_FOLDER_ID,
      name: SHARED_WITH_ME_FOLDER_NAME,
      description: SHARED_WITH_ME_FOLDER_DESCRIPTION,
      parent_id: null,
      flows: [],
      components: [],
      readonly: true,
      is_shared_folder: true,
    };
    const folders = [...data, sharedFolder];
    setMyCollectionId(myCollectionId ?? "");
    setFolders(folders);

    return folders;
  };

  const queryResult = query(["useGetFolders"], getFoldersFn, {
    ...options,
    enabled: isAuthenticated && (options?.enabled ?? true),
  });
  return queryResult;
};
