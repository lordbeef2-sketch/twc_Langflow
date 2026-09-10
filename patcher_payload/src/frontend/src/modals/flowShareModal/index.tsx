import { useEffect, useMemo, useState } from "react";
import IconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useGetShareableUsersQuery } from "@/controllers/API/queries/auth/use-get-shareable-users";
import {
  type FlowSharePermissionType,
  useCreateFlowShares,
} from "@/controllers/API/queries/flows/use-create-flow-shares";
import BaseModal from "@/modals/baseModal";
import useAlertStore from "@/stores/alertStore";
import type { FlowType } from "@/types/flow";

type FlowShareModalProps = {
  open: boolean;
  setOpen: (open: boolean) => void;
  flow?: FlowType;
};

export default function FlowShareModal({
  open,
  setOpen,
  flow,
}: FlowShareModalProps): JSX.Element {
  const [search, setSearch] = useState("");
  const [permission, setPermission] =
    useState<FlowSharePermissionType>("read");
  const [selectedRecipients, setSelectedRecipients] = useState<string[]>([]);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const { data: users = [], isLoading } = useGetShareableUsersQuery(
    {
      search,
      limit: 20,
    },
    {
      enabled: open,
      refetchOnWindowFocus: false,
    },
  );

  const { mutate: createFlowShares, isPending } = useCreateFlowShares();

  useEffect(() => {
    if (!open) {
      setSearch("");
      setPermission("read");
      setSelectedRecipients([]);
    }
  }, [open]);

  const selectedCountLabel = useMemo(() => {
    if (selectedRecipients.length === 0) {
      return "No recipients selected";
    }
    return `${selectedRecipients.length} recipient${selectedRecipients.length === 1 ? "" : "s"} selected`;
  }, [selectedRecipients.length]);

  const toggleRecipient = (userId: string) => {
    setSelectedRecipients((current) =>
      current.includes(userId)
        ? current.filter((recipientId) => recipientId !== userId)
        : [...current, userId],
    );
  };

  const handleShare = () => {
    if (!flow?.id || selectedRecipients.length === 0) {
      return;
    }

    createFlowShares(
      {
        flowId: flow.id,
        recipient_user_ids: selectedRecipients,
        permission,
      },
      {
        onSuccess: () => {
          setSuccessData({
            title: `Share invites sent for ${flow.name}`,
          });
          setOpen(false);
        },
        onError: (error: any) => {
          const detail =
            error?.response?.data?.detail ||
            error?.message ||
            "Could not share this flow";
          setErrorData({
            title: "Failed to share flow",
            list: [detail],
          });
        },
      },
    );
  };

  return (
    <BaseModal
      open={open}
      setOpen={setOpen}
      size="small-h-full"
      width="min(560px, calc(100vw - 2rem))"
      className="max-h-[80dvh]"
    >
      <BaseModal.Header description="Pick teammates, choose their access level, and send an invite they can accept or decline.">
        Share with users
      </BaseModal.Header>
      <BaseModal.Content className="min-h-0 gap-4 pr-1">
        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-sm font-medium">{flow?.name ?? "Current flow"}</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Recipients will get a prompt before this flow shows up in their
            shared workspace.
          </div>
        </div>

        <div className="space-y-3">
          <div className="text-sm font-medium">Access level</div>
          <RadioGroup
            value={permission}
            onValueChange={(value: FlowSharePermissionType) =>
              setPermission(value)
            }
            className="grid gap-2"
          >
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 hover:bg-muted/40">
              <RadioGroupItem value="read" className="mt-0.5" />
              <div>
                <div className="text-sm font-medium">Read access</div>
                <div className="text-xs text-muted-foreground">
                  Can open and review the flow, but can’t change it.
                </div>
              </div>
            </label>
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 hover:bg-muted/40">
              <RadioGroupItem value="edit" className="mt-0.5" />
              <div>
                <div className="text-sm font-medium">Edit access</div>
                <div className="text-xs text-muted-foreground">
                  Can edit the shared flow and save updates back to it.
                </div>
              </div>
            </label>
          </RadioGroup>
        </div>

        <div className="flex min-h-0 flex-col space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-medium">Recipients</div>
            <Badge variant="secondaryStatic" size="tag">
              {selectedCountLabel}
            </Badge>
          </div>
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users"
            icon="Search"
          />
          <div className="min-h-[220px] overflow-y-auto rounded-lg border">
            {isLoading ? (
              <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
                <IconComponent name="Loader2" className="h-4 w-4 animate-spin" />
                Loading users...
              </div>
            ) : users.length === 0 ? (
              <div className="px-4 py-6 text-sm text-muted-foreground">
                No matching users found.
              </div>
            ) : (
              <div className="divide-y">
                {users.map((user) => {
                  const isSelected = selectedRecipients.includes(user.id);
                  return (
                    <label
                      key={user.id}
                      className="flex cursor-pointer items-center gap-3 px-4 py-3 hover:bg-muted/30"
                    >
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => toggleRecipient(user.id)}
                      />
                      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-muted text-muted-foreground">
                        <IconComponent name="UserRound" className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {user.username}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </BaseModal.Content>
      <BaseModal.Footer className="mt-2 flex flex-col gap-3 sm:mt-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="text-xs text-muted-foreground sm:max-w-[55%]">
          They’ll need to accept before the flow appears for them.
        </div>
        <div className="flex w-full items-center justify-end gap-3 sm:w-auto">
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleShare}
            disabled={selectedRecipients.length === 0}
            loading={isPending}
          >
            Send invite
          </Button>
        </div>
      </BaseModal.Footer>
    </BaseModal>
  );
}
