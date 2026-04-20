import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useGetIncomingFlowSharesQuery } from "@/controllers/API/queries/flows/use-get-incoming-flow-shares";
import { useRespondToFlowShare } from "@/controllers/API/queries/flows/use-respond-to-flow-share";
import BaseModal from "@/modals/baseModal";
import useAlertStore from "@/stores/alertStore";
import { SHARED_WITH_ME_FOLDER_NAME } from "@/utils/flowAccess";

export default function FlowShareInvitePrompt(): JSX.Element {
  const [open, setOpen] = useState(false);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const { data: invites = [] } = useGetIncomingFlowSharesQuery({
    refetchInterval: 30000,
    refetchOnWindowFocus: true,
  });

  const { mutate: respondToFlowShare, isPending } = useRespondToFlowShare();

  const nextInvite = useMemo(() => invites[0], [invites]);

  useEffect(() => {
    if (nextInvite) {
      setOpen(true);
      return;
    }

    setOpen(false);
  }, [nextInvite]);

  const permissionLabel =
    nextInvite?.permission === "edit" ? "Can edit" : "Read only";

  const handleResponse = (accept: boolean) => {
    if (!nextInvite) {
      return;
    }

    respondToFlowShare(
      {
        shareId: nextInvite.id,
        accept,
      },
      {
        onSuccess: () => {
          setSuccessData({
            title: accept
              ? `${nextInvite.flow_name} is now in ${SHARED_WITH_ME_FOLDER_NAME}`
              : `Declined ${nextInvite.flow_name}`,
          });
          setOpen(false);
        },
        onError: (error: any) => {
          const detail =
            error?.response?.data?.detail ||
            error?.message ||
            "Could not respond to the share invite";
          setErrorData({
            title: "Share response failed",
            list: [detail],
          });
        },
      },
    );
  };

  if (!nextInvite) {
    return <></>;
  }

  return (
    <BaseModal
      open={open}
      setOpen={setOpen}
      size="x-small"
      closeButtonClassName="hidden"
    >
      <BaseModal.Header description="Accept to add this flow to your shared workspace, or decline to ignore it.">
        Flow share invite
      </BaseModal.Header>
      <BaseModal.Content className="gap-4">
        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-sm font-medium">{nextInvite.owner_username}</div>
          <div className="mt-1 text-sm text-muted-foreground">
            is sharing <span className="font-medium text-foreground">{nextInvite.flow_name}</span> with you.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondaryStatic" size="tag">
            {permissionLabel}
          </Badge>
          <span className="text-xs text-muted-foreground">
            Accepted flows appear in {SHARED_WITH_ME_FOLDER_NAME}.
          </span>
        </div>
      </BaseModal.Content>
      <BaseModal.Footer className="mt-4 flex items-center justify-end gap-3">
        <Button
          variant="outline"
          onClick={() => handleResponse(false)}
          disabled={isPending}
        >
          Decline
        </Button>
        <Button onClick={() => handleResponse(true)} loading={isPending}>
          Accept
        </Button>
      </BaseModal.Footer>
    </BaseModal>
  );
}
