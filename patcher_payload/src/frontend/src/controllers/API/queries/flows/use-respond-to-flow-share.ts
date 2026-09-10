import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface RespondToFlowSharePayload {
  shareId: string;
  accept: boolean;
}

export const useRespondToFlowShare: useMutationFunctionType<
  undefined,
  RespondToFlowSharePayload
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const respondToFlowShareFn = async ({
    shareId,
    accept,
  }: RespondToFlowSharePayload): Promise<any> => {
    const response = await api.patch(`${getURL("FLOWS")}/shares/${shareId}`, {
      accept,
    });
    return response.data;
  };

  const mutation: UseMutationResult<
    RespondToFlowSharePayload,
    any,
    RespondToFlowSharePayload
  > = mutate(["useRespondToFlowShare"], respondToFlowShareFn, {
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["useGetIncomingFlowSharesQuery"],
      });
      queryClient.invalidateQueries({
        queryKey: ["useGetRefreshFlowsQuery"],
      });
      queryClient.invalidateQueries({
        queryKey: ["useGetFolder"],
      });
    },
    ...options,
  });

  return mutation;
};
