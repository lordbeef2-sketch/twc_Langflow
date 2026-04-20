import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface HTTPSUploadRequest {
  file_type: "cert" | "key";
  file: File;
}

export interface HTTPSUploadResponse {
  file_type: string;
  file_path: string;
}

export const usePostHTTPSFileUpload: useMutationFunctionType<
  undefined,
  HTTPSUploadRequest,
  HTTPSUploadResponse
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  async function postHTTPSFileUpload(
    requestData: HTTPSUploadRequest,
  ): Promise<HTTPSUploadResponse> {
    const formData = new FormData();
    formData.append("file_type", requestData.file_type);
    formData.append("file", requestData.file);

    const res = await api.post(`${getURL("ADMIN_SETTINGS")}/https/upload`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data;
  }

  const mutation: UseMutationResult<HTTPSUploadResponse, any, HTTPSUploadRequest> =
    mutate(["usePostHTTPSFileUpload"], postHTTPSFileUpload, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["useGetHTTPSSettings"] });
      },
      ...options,
    });

  return mutation;
};
