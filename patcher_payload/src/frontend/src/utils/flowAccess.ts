import type { FlowType } from "@/types/flow";

export const SHARED_WITH_ME_FOLDER_ID = "__shared_with_me__";
export const SHARED_WITH_ME_FOLDER_NAME = "Shared with Me";
export const SHARED_WITH_ME_FOLDER_DESCRIPTION =
  "Flows other users have shared with you.";

export const getFlowViewerFolderId = (flow?: FlowType): string | undefined => {
  return flow?.viewer_folder_id ?? flow?.folder_id;
};

export const isFlowOwner = (flow?: FlowType): boolean => {
  return (flow?.current_user_permission ?? "owner") === "owner";
};

export const canEditFlow = (flow?: FlowType): boolean => {
  return (flow?.current_user_permission ?? "owner") !== "read";
};

export const isFlowReadOnly = (flow?: FlowType): boolean => {
  return !canEditFlow(flow);
};

export const getFlowPermissionLabel = (flow?: FlowType): string | null => {
  if (!flow?.current_user_permission || flow.current_user_permission === "owner") {
    return null;
  }
  return flow.current_user_permission === "edit" ? "Can edit" : "Read only";
};
