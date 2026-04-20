import * as Form from "@radix-ui/react-form";
import { useEffect, useMemo, useState } from "react";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  useGetSSOSettings,
  useGetSAMLMetadata,
  useGetSSOConfig,
  usePutSSOSettings,
  usePutSSOConfig,
  type UpsertSSOConfigRequest,
} from "@/controllers/API/queries/auth";
import useAlertStore from "@/stores/alertStore";

type SsoSettingsCardProps = {
  enabled: boolean;
  providerFilter?: "oauth" | "saml";
};

const DEFAULT_SSO_FORM: UpsertSSOConfigRequest = {
  provider: "oauth",
  provider_name: "oidc",
  enabled: true,
  enforce_sso: false,
  client_id: "",
  discovery_url: "",
  redirect_uri: "",
  scopes: "openid email profile",
  token_endpoint: "",
  authorization_endpoint: "",
  jwks_uri: "",
  issuer: "",
  saml_entity_id: "",
  saml_acs_url: "",
  saml_idp_metadata_url: "",
  saml_idp_entity_id: "",
  saml_sso_url: "",
  saml_slo_url: "",
  saml_x509_cert: "",
  saml_nameid_format: "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
  client_secret: "",
  email_claim: "email",
  username_claim: "preferred_username",
  user_id_claim: "sub",
};

export default function SsoSettingsCard({
  enabled,
  providerFilter,
}: SsoSettingsCardProps) {
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const [formState, setFormState] =
    useState<UpsertSSOConfigRequest>(DEFAULT_SSO_FORM);
  const [ssoEnabled, setSsoEnabled] = useState<boolean>(enabled);
  const [activeProviderName, setActiveProviderName] = useState<string>(
    DEFAULT_SSO_FORM.provider_name,
  );

  const { data: ssoSettings } = useGetSSOSettings({ enabled: true, retry: false });

  const { data: configs, isLoading: loadingConfigs } = useGetSSOConfig({
    enabled: ssoEnabled,
    retry: false,
  });

  const { mutate: saveSSOConfig, isPending } = usePutSSOConfig();
  const { mutate: saveSSOSettings, isPending: savingSSOSettings } =
    usePutSSOSettings();

  useEffect(() => {
    setSsoEnabled(enabled);
  }, [enabled]);

  useEffect(() => {
    if (typeof ssoSettings?.sso_enabled === "boolean") {
      setSsoEnabled(ssoSettings.sso_enabled);
    }
  }, [ssoSettings?.sso_enabled]);

  const activeConfig = useMemo(
    () =>
      configs?.find((config) => {
        if (config.provider_name !== activeProviderName) return false;
        if (!providerFilter) return true;
        if (providerFilter === "oauth") {
          return config.provider === "oauth" || config.provider === "oidc";
        }
        return config.provider === "saml";
      }),
    [configs, activeProviderName, providerFilter],
  );

  const filteredConfigs = useMemo(() => {
    if (!configs) return [];
    if (!providerFilter) return configs;
    if (providerFilter === "oauth") {
      return configs.filter(
        (config) => config.provider === "oauth" || config.provider === "oidc",
      );
    }
    return configs.filter((config) => config.provider === "saml");
  }, [configs, providerFilter]);

  const { data: samlMetadata, isFetching: loadingSAMLMetadata, refetch } =
    useGetSAMLMetadata(
      { providerName: formState.provider_name },
      {
        enabled:
          ssoEnabled &&
          formState.provider === "saml" &&
          Boolean(formState.provider_name),
        retry: false,
      },
    );

  const handleToggleSSO = (checked: boolean) => {
    saveSSOSettings(
      { sso_enabled: checked },
      {
        onSuccess: (response) => {
          setSsoEnabled(response.sso_enabled);
          setSuccessData({
            title: `SSO ${response.sso_enabled ? "enabled" : "disabled"}`,
          });
        },
        onError: (error: any) => {
          setErrorData({
            title: "SSO toggle error",
            list: [
              error?.response?.data?.detail ??
                "Unable to update SSO feature flag.",
            ],
          });
        },
      },
    );
  };

  useEffect(() => {
    if (!filteredConfigs || filteredConfigs.length === 0) {
      if (providerFilter) {
        setFormState((prev) => ({
          ...prev,
          provider: providerFilter === "oauth" ? "oauth" : "saml",
          client_secret: "",
        }));
      }
      return;
    }

    const selected =
      filteredConfigs.find(
        (config) => config.provider_name === activeProviderName,
      ) ?? filteredConfigs[0];

    setActiveProviderName(selected.provider_name);
    setFormState((prev) => ({
      ...prev,
      provider:
        providerFilter === "oauth"
          ? "oauth"
          : providerFilter === "saml"
            ? "saml"
            : ((selected.provider as "oauth" | "oidc" | "saml") ?? "oauth"),
      provider_name: selected.provider_name,
      enabled: selected.enabled,
      enforce_sso: selected.enforce_sso,
      client_id: selected.client_id ?? "",
      discovery_url: selected.discovery_url ?? "",
      redirect_uri: selected.redirect_uri ?? "",
      scopes: selected.scopes ?? "openid email profile",
      token_endpoint: selected.token_endpoint ?? "",
      authorization_endpoint: selected.authorization_endpoint ?? "",
      jwks_uri: selected.jwks_uri ?? "",
      issuer: selected.issuer ?? "",
      saml_entity_id: selected.saml_entity_id ?? "",
      saml_acs_url: selected.saml_acs_url ?? "",
      saml_idp_metadata_url: selected.saml_idp_metadata_url ?? "",
      saml_idp_entity_id: selected.saml_idp_entity_id ?? "",
      saml_sso_url: selected.saml_sso_url ?? "",
      saml_slo_url: selected.saml_slo_url ?? "",
      saml_x509_cert: selected.saml_x509_cert ?? "",
      saml_nameid_format:
        selected.saml_nameid_format ??
        "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
      email_claim: selected.email_claim,
      username_claim: selected.username_claim,
      user_id_claim: selected.user_id_claim,
      client_secret: "",
    }));
  }, [filteredConfigs, activeProviderName, providerFilter]);

  const updateField = (field: keyof UpsertSSOConfigRequest, value: string) => {
    setFormState((prev) => ({ ...prev, [field]: value }));
  };

  const handleSave = () => {
    const isOAuth = formState.provider === "oauth" || formState.provider === "oidc";
    const needsClientSecret = isOAuth && !activeConfig?.has_client_secret;

    if (needsClientSecret && !formState.client_secret?.trim()) {
      setErrorData({
        title: "SSO save error",
        list: ["Client secret is required when creating a new OAuth/OIDC provider."],
      });
      return;
    }

    if (
      formState.provider === "saml" &&
      (!formState.saml_entity_id?.trim() || !formState.saml_acs_url?.trim())
    ) {
      setErrorData({
        title: "SSO save error",
        list: ["SAML requires Entity ID and Assertion Consumer Service URL."],
      });
      return;
    }

    saveSSOConfig(formState, {
      onSuccess: () => {
        setSuccessData({ title: "SSO settings saved successfully" });
        setFormState((prev) => ({ ...prev, client_secret: "" }));
      },
      onError: (error: any) => {
        setErrorData({
          title: "SSO save error",
          list: [error?.response?.data?.detail ?? "Unable to save SSO settings."],
        });
      },
    });
  };

  if (!ssoEnabled) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Single Sign-On (SSO)</CardTitle>
          <CardDescription>
            Enable SSO from this toggle to manage OAuth/OIDC and SAML providers.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="text-sm font-medium">Enable SSO</p>
              <p className="text-xs text-muted-foreground">
                Turns on server-side SSO provider management.
              </p>
            </div>
            <Switch
              checked={ssoEnabled}
              onCheckedChange={handleToggleSSO}
              disabled={savingSSOSettings}
            />
          </div>
        </CardContent>
      </Card>
    );
  }

  const isSAML = formState.provider === "saml";
  const isOAuth = formState.provider === "oauth" || formState.provider === "oidc";

  return (
    <Form.Root
      onSubmit={(event) => {
        event.preventDefault();
        handleSave();
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle>Single Sign-On (SSO)</CardTitle>
          <CardDescription>
            Admin-only setup for OAuth/OIDC and SAML 2.0 providers.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="text-sm font-medium">Enable SSO</p>
              <p className="text-xs text-muted-foreground">
                Turns on server-side SSO provider management.
              </p>
            </div>
            <Switch
              checked={ssoEnabled}
              onCheckedChange={handleToggleSSO}
              disabled={savingSSOSettings}
            />
          </div>

          <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <Form.Field name="existing_provider">
              <Form.Label>Load Existing Provider</Form.Label>
              <select
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={activeProviderName}
                onChange={(event) => setActiveProviderName(event.target.value)}
              >
                <option value={formState.provider_name}>Current Draft</option>
                {filteredConfigs.map((config) => (
                  <option key={config.provider_name} value={config.provider_name}>
                    {config.provider_name} ({config.provider.toUpperCase()})
                  </option>
                ))}
              </select>
            </Form.Field>

            <Form.Field name="provider_name">
              <Form.Label>Provider Name</Form.Label>
              <Input
                value={formState.provider_name}
                onChange={(event) =>
                  updateField("provider_name", event.target.value)
                }
                placeholder="corp-sso"
                required
              />
            </Form.Field>
          </div>

          {!providerFilter && (
            <Tabs
              value={formState.provider}
              onValueChange={(value) =>
                setFormState((prev) => ({
                  ...prev,
                  provider: value as "oauth" | "oidc" | "saml",
                }))
              }
              className="mb-4"
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="oauth">OAuth / OIDC</TabsTrigger>
                <TabsTrigger value="saml">SAML 2.0</TabsTrigger>
              </TabsList>
            </Tabs>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {isOAuth && (
              <>
                <Form.Field name="client_id">
                  <Form.Label>Client ID</Form.Label>
                  <Input
                    value={formState.client_id}
                    onChange={(event) =>
                      updateField("client_id", event.target.value)
                    }
                    placeholder="client-id"
                    required
                  />
                </Form.Field>

                <Form.Field name="redirect_uri">
                  <Form.Label>Redirect URI</Form.Label>
                  <Input
                    value={formState.redirect_uri}
                    onChange={(event) =>
                      updateField("redirect_uri", event.target.value)
                    }
                    placeholder="http://localhost:7860/api/v1/sso/callback"
                    required
                  />
                </Form.Field>

                <Form.Field name="client_secret" className="md:col-span-2">
                  <Form.Label>Client Secret</Form.Label>
                  <Input
                    type="password"
                    value={formState.client_secret}
                    onChange={(event) =>
                      updateField("client_secret", event.target.value)
                    }
                    placeholder={
                      activeConfig?.has_client_secret
                        ? "Leave empty to keep existing secret"
                        : "Enter client secret"
                    }
                  />
                </Form.Field>

                <Form.Field name="discovery_url" className="md:col-span-2">
                  <Form.Label>Discovery URL (optional)</Form.Label>
                  <Input
                    value={formState.discovery_url}
                    onChange={(event) =>
                      updateField("discovery_url", event.target.value)
                    }
                    placeholder="https://example.com/.well-known/openid-configuration"
                  />
                </Form.Field>

                <Form.Field name="authorization_endpoint" className="md:col-span-2">
                  <Form.Label>Authorization Endpoint</Form.Label>
                  <Input
                    value={formState.authorization_endpoint}
                    onChange={(event) =>
                      updateField("authorization_endpoint", event.target.value)
                    }
                    placeholder="https://idp.example.com/oauth2/authorize"
                  />
                </Form.Field>

                <Form.Field name="token_endpoint" className="md:col-span-2">
                  <Form.Label>Token Endpoint</Form.Label>
                  <Input
                    value={formState.token_endpoint}
                    onChange={(event) =>
                      updateField("token_endpoint", event.target.value)
                    }
                    placeholder="https://idp.example.com/oauth2/token"
                  />
                </Form.Field>

                <Form.Field name="jwks_uri" className="md:col-span-2">
                  <Form.Label>JWKS URI</Form.Label>
                  <Input
                    value={formState.jwks_uri}
                    onChange={(event) =>
                      updateField("jwks_uri", event.target.value)
                    }
                    placeholder="https://idp.example.com/.well-known/jwks.json"
                  />
                </Form.Field>

                <Form.Field name="issuer" className="md:col-span-2">
                  <Form.Label>Issuer</Form.Label>
                  <Input
                    value={formState.issuer}
                    onChange={(event) => updateField("issuer", event.target.value)}
                    placeholder="https://idp.example.com"
                  />
                </Form.Field>

                <Form.Field name="scopes" className="md:col-span-2">
                  <Form.Label>Scopes</Form.Label>
                  <Input
                    value={formState.scopes}
                    onChange={(event) => updateField("scopes", event.target.value)}
                    placeholder="openid email profile"
                    required
                  />
                </Form.Field>
              </>
            )}

            {isSAML && (
              <>
                <Form.Field name="saml_entity_id" className="md:col-span-2">
                  <Form.Label>SP Entity ID</Form.Label>
                  <Input
                    value={formState.saml_entity_id}
                    onChange={(event) =>
                      updateField("saml_entity_id", event.target.value)
                    }
                    placeholder="urn:langflow:sp"
                    required
                  />
                </Form.Field>

                <Form.Field name="saml_acs_url" className="md:col-span-2">
                  <Form.Label>Assertion Consumer Service (ACS) URL</Form.Label>
                  <Input
                    value={formState.saml_acs_url}
                    onChange={(event) =>
                      updateField("saml_acs_url", event.target.value)
                    }
                    placeholder="https://langflow.example.com/api/v1/sso/callback"
                    required
                  />
                </Form.Field>

                <Form.Field name="saml_idp_metadata_url" className="md:col-span-2">
                  <Form.Label>IdP Metadata URL</Form.Label>
                  <Input
                    value={formState.saml_idp_metadata_url}
                    onChange={(event) =>
                      updateField("saml_idp_metadata_url", event.target.value)
                    }
                    placeholder="https://idp.example.com/metadata"
                  />
                </Form.Field>

                <Form.Field name="saml_idp_entity_id" className="md:col-span-2">
                  <Form.Label>IdP Entity ID</Form.Label>
                  <Input
                    value={formState.saml_idp_entity_id}
                    onChange={(event) =>
                      updateField("saml_idp_entity_id", event.target.value)
                    }
                    placeholder="urn:idp:example"
                  />
                </Form.Field>

                <Form.Field name="saml_sso_url" className="md:col-span-2">
                  <Form.Label>IdP SSO URL</Form.Label>
                  <Input
                    value={formState.saml_sso_url}
                    onChange={(event) =>
                      updateField("saml_sso_url", event.target.value)
                    }
                    placeholder="https://idp.example.com/sso"
                  />
                </Form.Field>

                <Form.Field name="saml_slo_url" className="md:col-span-2">
                  <Form.Label>IdP SLO URL</Form.Label>
                  <Input
                    value={formState.saml_slo_url}
                    onChange={(event) =>
                      updateField("saml_slo_url", event.target.value)
                    }
                    placeholder="https://idp.example.com/slo"
                  />
                </Form.Field>

                <Form.Field name="saml_nameid_format" className="md:col-span-2">
                  <Form.Label>NameID Format</Form.Label>
                  <Input
                    value={formState.saml_nameid_format}
                    onChange={(event) =>
                      updateField("saml_nameid_format", event.target.value)
                    }
                    placeholder="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
                  />
                </Form.Field>

                <Form.Field name="saml_x509_cert" className="md:col-span-2">
                  <Form.Label>IdP X.509 Certificate (PEM)</Form.Label>
                  <Textarea
                    value={formState.saml_x509_cert}
                    onChange={(event) =>
                      updateField("saml_x509_cert", event.target.value)
                    }
                    placeholder="-----BEGIN CERTIFICATE----- ..."
                    rows={5}
                  />
                </Form.Field>
              </>
            )}

            <Form.Field name="email_claim">
              <Form.Label>Email Claim</Form.Label>
              <Input
                value={formState.email_claim}
                onChange={(event) => updateField("email_claim", event.target.value)}
                placeholder="email"
                required
              />
            </Form.Field>

            <Form.Field name="username_claim">
              <Form.Label>Username Claim</Form.Label>

          {isSAML && (
            <div className="mt-4 rounded-md border p-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium">SAML Metadata Viewer</p>
                  <p className="text-xs text-muted-foreground">
                    Preview and export SP metadata XML for your IdP setup.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      void refetch();
                    }}
                    loading={loadingSAMLMetadata}
                  >
                    Refresh Metadata
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      const url = `/api/v1/sso/config/${encodeURIComponent(formState.provider_name)}/saml/metadata.xml`;
                      window.open(url, "_blank", "noopener,noreferrer");
                    }}
                    disabled={!formState.provider_name}
                  >
                    Export XML
                  </Button>
                </div>
              </div>
              <Textarea
                value={samlMetadata?.metadata_xml ?? "Save and refresh to generate metadata."}
                rows={10}
                readOnly
              />
            </div>
          )}
              <Input
                value={formState.username_claim}
                onChange={(event) =>
                  updateField("username_claim", event.target.value)
                }
                placeholder="preferred_username"
                required
              />
            </Form.Field>

            <Form.Field name="user_id_claim">
              <Form.Label>User ID Claim</Form.Label>
              <Input
                value={formState.user_id_claim}
                onChange={(event) => updateField("user_id_claim", event.target.value)}
                placeholder="sub"
                required
              />
            </Form.Field>

            <div className="flex items-center justify-between rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Provider Enabled</p>
                <p className="text-xs text-muted-foreground">
                  Allow this provider for SSO login.
                </p>
              </div>
              <Switch
                checked={formState.enabled}
                onCheckedChange={(checked) =>
                  setFormState((prev) => ({ ...prev, enabled: checked }))
                }
              />
            </div>

            <div className="flex items-center justify-between rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Enforce SSO</p>
                <p className="text-xs text-muted-foreground">
                  Block password login when enabled.
                </p>
              </div>
              <Switch
                checked={formState.enforce_sso}
                onCheckedChange={(checked) =>
                  setFormState((prev) => ({ ...prev, enforce_sso: checked }))
                }
              />
            </div>
          </div>

          {loadingConfigs && (
            <p className="mt-4 text-xs text-muted-foreground">
              Loading existing SSO configuration...
            </p>
          )}
        </CardContent>
        <CardFooter className="border-t px-6 py-4">
          <Form.Submit asChild>
            <Button type="submit" loading={isPending}>
              Save SSO Settings
            </Button>
          </Form.Submit>
        </CardFooter>
      </Card>
    </Form.Root>
  );
}
