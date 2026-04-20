import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type FlowSharePermissionType = "read" | "edit";

export interface CreateFlowSharesPayload {
  flowId: string;
  recipient_user_ids: string[];
  permission: FlowSharePermissionType;
}

export const useCreateFlowShares: useMutationFunctionType<
  undefined,
  CreateFlowSharesPayload
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const createFlowSharesFn = async ({
    flowId,
    ...payload
  }: CreateFlowSharesPayload): Promise<any> => {
    const response = await api.post(`${getURL("FLOWS")}/${flowId}/shares`, payload);
    return response.data;
  };

  const mutation: UseMutationResult<
    CreateFlowSharesPayload,
    any,
    CreateFlowSharesPayload
  > = mutate(["useCreateFlowShares"], createFlowSharesFn, {
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["useGetIncomingFlowSharesQuery"],
      });
    },
    ...options,
  });

  return mutation;
};
