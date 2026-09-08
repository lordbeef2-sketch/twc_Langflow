import type { FlowType } from "@/types/flow";

export const SHARED_WITH_ME_FOLDER_ID = "__shared_with_me__";
export const SHARED_WITH_ME_FOLDER_NAME = "Shared with Me";
export const SHARED_WITH_ME_FOLDER_DESCRIPTION =
  "Flows other users have shared with you.";
export const ALL_WORKFLOWS_FOLDER_ID = "__all_workflows__";
export const ALL_WORKFLOWS_FOLDER_NAME = "All Workflows";
export const ALL_WORKFLOWS_FOLDER_DESCRIPTION =
  "Read-only access to workflows owned by other users.";

export const getFlowViewerFolderId = (flow?: FlowType): string | undefined => {
  return flow?.viewer_folder_id ?? flow?.folder_id;
};

export const isFlowOwner = (flow?: FlowType): boolean => {
  return (flow?.current_user_permission ?? "owner") === "owner";
};

export const canEditFlow = (flow?: FlowType): boolean => {
  return ["owner", "edit"].includes(flow?.current_user_permission ?? "owner");
};

export const isFlowReadOnly = (flow?: FlowType): boolean => {
  return !canEditFlow(flow);
};

export const getFlowPermissionLabel = (flow?: FlowType): string | null => {
  if (!flow?.current_user_permission || flow.current_user_permission === "owner") {
    return null;
  }
  if (flow.current_user_permission === "edit") {
    return "Can edit";
  }
  if (flow.current_user_permission === "global_read") {
    return "All workflows access";
  }
  return "Read only";
};
