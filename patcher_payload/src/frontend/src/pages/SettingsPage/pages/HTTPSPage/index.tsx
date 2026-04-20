import * as Form from "@radix-ui/react-form";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  useGetHTTPSSettings,
  usePostHTTPSFileUpload,
  usePutHTTPSSettings,
  type HTTPSSettingsUpdateRequest,
} from "@/controllers/API/queries/auth";
import useAlertStore from "@/stores/alertStore";

const DEFAULT_FORM: HTTPSSettingsUpdateRequest = {
  ssl_enabled: false,
  ssl_cert_file: "",
  ssl_key_file: "",
  host: "127.0.0.1",
  port: 7860,
  https_hsts_enabled: false,
  https_hsts_max_age: 31536000,
  https_hsts_include_subdomains: false,
  https_hsts_preload: false,
};

export default function HTTPSPage(): JSX.Element {
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [formState, setFormState] =
    useState<HTTPSSettingsUpdateRequest>(DEFAULT_FORM);

  const { data, isLoading } = useGetHTTPSSettings({ retry: false });
  const { mutate: saveHTTPSSettings, isPending } = usePutHTTPSSettings();
  const { mutate: uploadHTTPSFile, isPending: uploadingFile } =
    usePostHTTPSFileUpload();

  useEffect(() => {
    if (!data) return;

    setFormState({
      ssl_enabled: data.ssl_enabled,
      ssl_cert_file: data.ssl_cert_file ?? "",
      ssl_key_file: data.ssl_key_file ?? "",
      host: data.host,
      port: data.port,
      https_hsts_enabled: data.https_hsts_enabled,
      https_hsts_max_age: data.https_hsts_max_age,
      https_hsts_include_subdomains: data.https_hsts_include_subdomains,
      https_hsts_preload: data.https_hsts_preload,
    });
  }, [data]);

  const handleUploadFile = (kind: "cert" | "key", file?: File) => {
    if (!file) return;

    uploadHTTPSFile(
      { file_type: kind, file },
      {
        onSuccess: (response) => {
          if (kind === "cert") {
            setFormState((prev) => ({ ...prev, ssl_cert_file: response.file_path }));
          } else {
            setFormState((prev) => ({ ...prev, ssl_key_file: response.file_path }));
          }
          setSuccessData({
            title: `Uploaded ${kind === "cert" ? "certificate" : "private key"} successfully`,
          });
        },
        onError: (error: any) => {
          setErrorData({
            title: "HTTPS upload error",
            list: [error?.response?.data?.detail ?? "Unable to upload file."],
          });
        },
      },
    );
  };

  const handleSave = () => {
    if (formState.ssl_enabled) {
      if (!formState.ssl_cert_file?.trim() || !formState.ssl_key_file?.trim()) {
        setErrorData({
          title: "HTTPS save error",
          list: ["Certificate and key file paths are required when HTTPS is enabled."],
        });
        return;
      }
    }

    saveHTTPSSettings(formState, {
      onSuccess: () => {
        setSuccessData({
          title: "HTTPS settings saved. Restart Langflow to apply TLS changes.",
        });
      },
      onError: (error: any) => {
        setErrorData({
          title: "HTTPS save error",
          list: [
            error?.response?.data?.detail ??
              "Unable to save HTTPS settings.",
          ],
        });
      },
    });
  };

  return (
    <Form.Root
      onSubmit={(event) => {
        event.preventDefault();
        handleSave();
      }}
    >
      <div className="flex h-full w-full flex-col gap-6 overflow-x-hidden">
        <div className="flex w-full items-center justify-between gap-4 space-y-0.5">
          <div className="flex w-full flex-col">
            <h2
              className="flex items-center text-lg font-semibold tracking-tight"
              data-testid="settings_https_header"
            >
              HTTPS Configuration
            </h2>
            <p className="text-sm text-muted-foreground">
              Admin-only TLS setup for Langflow server endpoint and secure cookies.
            </p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Transport Security (TLS)</CardTitle>
            <CardDescription>
              Configure certificate and key paths. Restart is required after saving
              HTTPS changes.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="md:col-span-2 flex items-center justify-between rounded-md border p-3">
                <div>
                  <p className="text-sm font-medium">Enable HTTPS</p>
                  <p className="text-xs text-muted-foreground">
                    Requires valid certificate and private key files.
                  </p>
                </div>
                <Switch
                  checked={formState.ssl_enabled}
                  onCheckedChange={(checked) =>
                    setFormState((prev) => ({ ...prev, ssl_enabled: checked }))
                  }
                />
              </div>

              <Form.Field name="host">
                <Form.Label>Host</Form.Label>
                <Input
                  value={formState.host ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, host: event.target.value }))
                  }
                  placeholder="127.0.0.1"
                  required
                />
              </Form.Field>

              <Form.Field name="port">
                <Form.Label>Port</Form.Label>
                <Input
                  type="number"
                  min={1}
                  max={65535}
                  value={formState.port ?? 7860}
                  onChange={(event) =>
                    setFormState((prev) => ({
                      ...prev,
                      port: Number(event.target.value || 7860),
                    }))
                  }
                  required
                />
              </Form.Field>

              <Form.Field name="ssl_cert_file" className="md:col-span-2">
                <Form.Label>SSL Certificate File</Form.Label>
                <Input
                  value={formState.ssl_cert_file ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => ({
                      ...prev,
                      ssl_cert_file: event.target.value,
                    }))
                  }
                  placeholder="C:\\certs\\langflow.crt"
                  disabled={!formState.ssl_enabled}
                />
                <Input
                  type="file"
                  accept=".crt,.pem,.cer"
                  onChange={(event) =>
                    handleUploadFile("cert", event.target.files?.[0])
                  }
                  disabled={!formState.ssl_enabled}
                />
              </Form.Field>

              <Form.Field name="ssl_key_file" className="md:col-span-2">
                <Form.Label>SSL Key File</Form.Label>
                <Input
                  value={formState.ssl_key_file ?? ""}
                  onChange={(event) =>
                    setFormState((prev) => ({
                      ...prev,
                      ssl_key_file: event.target.value,
                    }))
                  }
                  placeholder="C:\\certs\\langflow.key"
                  disabled={!formState.ssl_enabled}
                />
                <Input
                  type="file"
                  accept=".key,.pem"
                  onChange={(event) =>
                    handleUploadFile("key", event.target.files?.[0])
                  }
                  disabled={!formState.ssl_enabled}
                />
              </Form.Field>

              <div className="md:col-span-2 mt-2 rounded-md border p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">HSTS Hardening</p>
                    <p className="text-xs text-muted-foreground">
                      Adds Strict-Transport-Security header for HTTPS responses.
                    </p>
                  </div>
                  <Switch
                    checked={Boolean(formState.https_hsts_enabled)}
                    onCheckedChange={(checked) =>
                      setFormState((prev) => ({
                        ...prev,
                        https_hsts_enabled: checked,
                      }))
                    }
                  />
                </div>

                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
                  <Form.Field name="https_hsts_max_age">
                    <Form.Label>HSTS Max Age (seconds)</Form.Label>
                    <Input
                      type="number"
                      min={0}
                      max={63072000}
                      value={formState.https_hsts_max_age ?? 31536000}
                      onChange={(event) =>
                        setFormState((prev) => ({
                          ...prev,
                          https_hsts_max_age: Number(event.target.value || 0),
                        }))
                      }
                      disabled={!formState.https_hsts_enabled}
                    />
                  </Form.Field>

                  <div className="flex items-center justify-between rounded-md border p-3">
                    <p className="text-sm">Include Subdomains</p>
                    <Switch
                      checked={Boolean(formState.https_hsts_include_subdomains)}
                      onCheckedChange={(checked) =>
                        setFormState((prev) => ({
                          ...prev,
                          https_hsts_include_subdomains: checked,
                        }))
                      }
                      disabled={!formState.https_hsts_enabled}
                    />
                  </div>

                  <div className="flex items-center justify-between rounded-md border p-3">
                    <p className="text-sm">Preload</p>
                    <Switch
                      checked={Boolean(formState.https_hsts_preload)}
                      onCheckedChange={(checked) =>
                        setFormState((prev) => ({
                          ...prev,
                          https_hsts_preload: checked,
                        }))
                      }
                      disabled={!formState.https_hsts_enabled}
                    />
                  </div>
                </div>
              </div>
            </div>

            {data && (
              <div className="mt-4 rounded-md border p-3 text-sm">
                <p className="font-medium">Current Runtime Security</p>
                <p className="text-muted-foreground">
                  Access cookie secure flag: {data.access_secure_cookie ? "Enabled" : "Disabled"}
                </p>
                <p className="text-muted-foreground">
                  Refresh cookie secure flag: {data.refresh_secure_cookie ? "Enabled" : "Disabled"}
                </p>
              </div>
            )}

            {isLoading && (
              <p className="mt-4 text-xs text-muted-foreground">
                Loading HTTPS settings...
              </p>
            )}
          </CardContent>
          <CardFooter className="border-t px-6 py-4">
            <Form.Submit asChild>
              <Button type="submit" loading={isPending}>
                Save HTTPS Settings
              </Button>
            </Form.Submit>
            {uploadingFile && (
              <p className="ml-3 text-xs text-muted-foreground">Uploading certificate/key...</p>
            )}
          </CardFooter>
        </Card>
      </div>
    </Form.Root>
  );
}
