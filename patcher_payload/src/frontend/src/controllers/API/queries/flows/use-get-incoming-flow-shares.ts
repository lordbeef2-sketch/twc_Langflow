import type { UseQueryOptions } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type IncomingFlowShareType = {
  id: string;
  flow_id: string;
  flow_name: string;
  owner_user_id: string;
  owner_username: string;
  permission: "read" | "edit";
  status: "pending" | "accepted" | "rejected";
  created_at: string;
  responded_at?: string | null;
};

export const useGetIncomingFlowSharesQuery: useQueryFunctionType<
  undefined,
  IncomingFlowShareType[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const getIncomingFlowSharesFn = async (): Promise<IncomingFlowShareType[]> => {
    const response = await api.get<IncomingFlowShareType[]>(
      `${getURL("FLOWS")}/shared/incoming`,
    );
    return response.data;
  };

  return query(
    ["useGetIncomingFlowSharesQuery"],
    getIncomingFlowSharesFn,
    options as UseQueryOptions,
  );
};
