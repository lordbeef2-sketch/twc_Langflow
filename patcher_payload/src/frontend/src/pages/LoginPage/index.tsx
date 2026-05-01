import * as Form from "@radix-ui/react-form";
import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import LangflowLogo from "@/assets/LangflowLogo.svg?react";
import {
  useGetTWCServers,
  useLoginUser,
} from "@/controllers/API/queries/auth";
import { getURL } from "@/controllers/API/helpers/constants";
import { CustomLink } from "@/customization/components/custom-link";
import { useSanitizeRedirectUrl } from "@/hooks/use-sanitize-redirect-url";
import InputComponent from "../../components/core/parameterRenderComponent/components/inputComponent";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { CONTROL_LOGIN_STATE } from "../../constants/constants";
import { AuthContext } from "../../contexts/authContext";
import useAlertStore from "../../stores/alertStore";
import type { LoginType } from "../../types/api";
import type {
  inputHandlerEventType,
  loginInputStateType,
} from "../../types/components";

const REDIRECT_SESSION_KEY = "langflow_login_redirect";

export default function LoginPage(): JSX.Element {
  const [inputState, setInputState] =
    useState<loginInputStateType>(CONTROL_LOGIN_STATE);
  const [selectedServerId, setSelectedServerId] = useState("");
  const [isRedirectingToTWC, setIsRedirectingToTWC] = useState(false);
  const [searchParams] = useSearchParams();

  const { password, username } = inputState;

  useSanitizeRedirectUrl();

  const { t } = useTranslation();
  const { login, clearAuthSession } = useContext(AuthContext);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const twcError = searchParams.get("twc_error");

  function handleInput({
    target: { name, value },
  }: inputHandlerEventType): void {
    setInputState((prev) => ({ ...prev, [name]: value }));
  }

  const { mutate } = useLoginUser();
  const queryClient = useQueryClient();
  const { data: twcServersData } = useGetTWCServers();

  const readyTWCServers = useMemo(
    () => twcServersData?.servers?.filter((server) => server.ready) ?? [],
    [twcServersData],
  );

  useEffect(() => {
    if (!readyTWCServers.length) {
      setSelectedServerId("");
      return;
    }

    const preferredServer =
      twcServersData?.default_server_id ||
      readyTWCServers.find((server) => server.id === selectedServerId)?.id ||
      readyTWCServers[0]?.id ||
      "";
    setSelectedServerId(preferredServer);
  }, [readyTWCServers, selectedServerId, twcServersData?.default_server_id]);

  function signIn() {
    const user: LoginType = {
      username: username.trim(),
      password: password.trim(),
    };

    mutate(user, {
      onSuccess: (data) => {
        clearAuthSession();
        login(data.access_token, "login", data.refresh_token);
        queryClient.clear();
      },
      onError: (error) => {
        setErrorData({
          title: t("errors.signin"),
          list: [error["response"]["data"]["detail"]],
        });
      },
    });
  }

  function startTWCSignIn() {
    if (!selectedServerId) {
      return;
    }
    setIsRedirectingToTWC(true);

    const nextPath = sessionStorage.getItem(REDIRECT_SESSION_KEY) || "/";
    const query = new URLSearchParams();
    if (nextPath && nextPath !== "/") {
      query.set("next", nextPath);
    }

    const baseUrl = `${getURL("TWC_AUTH")}/signin/${encodeURIComponent(
      selectedServerId,
    )}`;
    const targetUrl = query.toString()
      ? `${baseUrl}?${query.toString()}`
      : baseUrl;

    window.location.assign(targetUrl);
  }

  const hasTWCServers = Boolean(twcServersData?.enabled);
  const hasReadyTWCServer = readyTWCServers.length > 0;
  const configurationError =
    hasTWCServers && !hasReadyTWCServer
      ? twcServersData?.servers?.find((server) => !server.ready)?.error ||
        "No valid Teamwork Cloud server is configured."
      : null;

  return (
    <Form.Root
      onSubmit={(event) => {
        if (password === "") {
          event.preventDefault();
          return;
        }
        signIn();
        event.preventDefault();
      }}
      className="h-screen w-full"
    >
      <div className="flex h-full w-full flex-col items-center justify-center bg-muted">
        <div className="flex w-80 max-w-[90vw] flex-col items-center justify-center gap-2">
          <LangflowLogo
            title="Langflow logo"
            className="mb-4 h-10 w-10 scale-[1.5]"
          />
          <span className="mb-6 text-2xl font-semibold text-primary">
            {t("auth.loginTitle")}
          </span>
          <div className="mb-3 w-full">
            <Form.Field name="username">
              <Form.Label className="data-[invalid]:label-invalid">
                {t("auth.usernameLabel")}{" "}
                <span className="font-medium text-destructive">*</span>
              </Form.Label>

              <Form.Control asChild>
                <Input
                  type="username"
                  onChange={({ target: { value } }) => {
                    handleInput({ target: { name: "username", value } });
                  }}
                  value={username}
                  className="w-full"
                  required
                  placeholder={t("auth.usernamePlaceholder")}
                />
              </Form.Control>

              <Form.Message match="valueMissing" className="field-invalid">
                {t("auth.usernameRequired")}
              </Form.Message>
            </Form.Field>
          </div>
          <div className="mb-3 w-full">
            <Form.Field name="password">
              <Form.Label className="data-[invalid]:label-invalid">
                {t("auth.passwordLabel")}{" "}
                <span className="font-medium text-destructive">*</span>
              </Form.Label>

              <InputComponent
                onChange={(value) => {
                  handleInput({ target: { name: "password", value } });
                }}
                value={password}
                isForm
                password={true}
                required
                placeholder={t("auth.passwordPlaceholder")}
                className="w-full"
              />

              <Form.Message className="field-invalid" match="valueMissing">
                {t("auth.passwordRequired")}
              </Form.Message>
            </Form.Field>
          </div>
          <div className="w-full">
            <Form.Submit asChild>
              <Button className="mr-3 mt-6 w-full" type="submit">
                {t("auth.signInButton")}
              </Button>
            </Form.Submit>
          </div>
          <div className="w-full">
            <CustomLink to="/signup">
              <Button className="w-full" variant="outline" type="button">
                {t("auth.noAccount")}&nbsp;<b>{t("auth.signUpLink")}</b>
              </Button>
            </CustomLink>
          </div>

          {hasTWCServers && (
            <div className="mt-6 w-full rounded-lg border border-border bg-background p-4 shadow-sm">
              <div className="mb-3 text-center">
                <div className="text-sm font-semibold text-foreground">
                  Sign in via TWC
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  Use Teamwork Cloud Authentication Server and your existing IdP
                  sign-in.
                </div>
              </div>

              {twcError && (
                <div className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                  {twcError}
                </div>
              )}

              {configurationError ? (
                <div className="rounded-md border border-border bg-muted px-3 py-2 text-sm text-muted-foreground">
                  {configurationError}
                </div>
              ) : (
                <>
                  {readyTWCServers.length > 1 && (
                    <div className="mb-3 w-full">
                      <label
                        htmlFor="twc-server"
                        className="mb-1 block text-sm font-medium text-foreground"
                      >
                        Teamwork Cloud server
                      </label>
                      <select
                        id="twc-server"
                        value={selectedServerId}
                        onChange={(event) =>
                          setSelectedServerId(event.target.value)
                        }
                        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm outline-none"
                      >
                        {readyTWCServers.map((server) => (
                          <option key={server.id} value={server.id}>
                            {server.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <Button
                    className="w-full"
                    type="button"
                    variant="secondary"
                    disabled={!selectedServerId || isRedirectingToTWC}
                    onClick={startTWCSignIn}
                  >
                    {isRedirectingToTWC
                      ? "Redirecting to TWC..."
                      : "Sign in via TWC"}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </Form.Root>
  );
}
