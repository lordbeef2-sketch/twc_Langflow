import type { ConfigResponse } from "@/controllers/API/queries/config/use-get-config";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type AuthSecuritySettingsCardProps = {
  config: ConfigResponse;
};

export default function AuthSecuritySettingsCard({
  config,
}: AuthSecuritySettingsCardProps): JSX.Element {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Authentication Security</CardTitle>
        <CardDescription>
          Current authentication and account policy values loaded from server
          settings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Public Sign Up</p>
            <p className="font-medium">
              {config.enable_public_signup ? "Enabled" : "Disabled"}
            </p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Password Minimum Length</p>
            <p className="font-medium">{config.password_min_length}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">
              Password Character Classes
            </p>
            <p className="font-medium">{config.password_min_character_classes}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Login Max Attempts</p>
            <p className="font-medium">{config.login_max_attempts}</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Login Attempt Window</p>
            <p className="font-medium">
              {config.login_attempt_window_seconds} seconds
            </p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">Lockout Duration</p>
            <p className="font-medium">{config.login_lockout_seconds} seconds</p>
          </div>
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">SSO Feature Flag</p>
            <p className="font-medium">
              {config.sso_enabled ? "Enabled" : "Disabled"}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}