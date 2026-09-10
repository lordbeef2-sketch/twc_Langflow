import { truncate } from "lodash";
import { useCallback, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ConfirmationModal from "../confirmationModal";

export function SaveChangesModal({
  onSave,
  onProceed,
  onCancel,
  flowName,
  lastSaved,
  readOnly,
}: {
  onSave: () => Promise<void>;
  onProceed: () => void;
  onCancel: () => void;
  flowName: string;
  lastSaved: string | undefined;
  readOnly?: boolean;
}): JSX.Element {
  const [saving, setSaving] = useState(false);

  const handleOpenAutoFocus = useCallback((e: Event) => {
    e.preventDefault();
    (
      document.querySelector('[data-testid="replace-button"]') as HTMLElement
    )?.focus();
  }, []);

  return (
    <ConfirmationModal
      open={true}
      onClose={onCancel}
      destructiveCancel
      title={truncate(flowName, { length: 32 }) + " has unsaved changes"}
      cancelText={readOnly ? "Discard changes" : "Exit anyway"}
      confirmationText={readOnly ? undefined : "Save and Exit"}
      onConfirm={
        readOnly
          ? undefined
          : async () => {
              setSaving(true);
              try {
                await onSave();
              } finally {
                setSaving(false);
              }
            }
      }
      onCancel={onProceed}
      loading={saving}
      size="x-small"
      onOpenAutoFocus={handleOpenAutoFocus}
    >
      <ConfirmationModal.Content>
        <div className="mb-4 flex w-full items-center gap-3 rounded-md bg-warning px-4 py-2 text-warning-foreground">
          <ForwardedIconComponent name="Info" className="h-5 w-5" />
          Last saved: {lastSaved ?? "Never"}
        </div>
        {readOnly
          ? "You have read-only access to this flow, so your local changes can’t be saved. Discard them to leave."
          : "Unsaved changes will be permanently lost if you leave without saving."}
      </ConfirmationModal.Content>
    </ConfirmationModal>
  );
}
