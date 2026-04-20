import { isFullConfig, useGetConfig } from "@/controllers/API/queries/config/use-get-config";
import useAuthStore from "@/stores/authStore";
import SsoSettingsCard from "../GeneralPage/components/SsoSettingsCard";

export default function OAuthSSOPage(): JSX.Element {
  const isAdmin = useAuthStore((state) => state.isAdmin);
  const { data: configData } = useGetConfig({ enabled: isAdmin });

  return (
    <div className="flex h-full w-full flex-col gap-6 overflow-x-hidden">
      <div className="flex w-full items-center justify-between gap-4 space-y-0.5">
        <div className="flex w-full flex-col">
          <h2
            className="flex items-center text-lg font-semibold tracking-tight"
            data-testid="settings_oauth_sso_header"
          >
            OAuth / OIDC SSO
          </h2>
          <p className="text-sm text-muted-foreground">
            Admin-only setup for OAuth/OIDC providers.
          </p>
        </div>
      </div>

      {configData && isFullConfig(configData) && (
        <SsoSettingsCard
          enabled={configData.sso_enabled}
          providerFilter="oauth"
        />
      )}
    </div>
  );
}
