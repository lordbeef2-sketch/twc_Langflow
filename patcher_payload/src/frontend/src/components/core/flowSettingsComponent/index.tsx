import * as Form from "@radix-ui/react-form";
import { cloneDeep } from "lodash";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { FlowType } from "@/types/flow";
import { canEditFlow } from "@/utils/flowAccess";
import EditFlowSettings from "../editFlowSettingsComponent";

type FlowSettingsComponentProps = {
  flowData?: FlowType;
  close: () => void;
  open: boolean;
};

const updateFlowWithFormValues = (
  baseFlow: FlowType,
  newName: string,
  newDescription: string,
  newLocked: boolean,
): FlowType => {
  const newFlow = cloneDeep(baseFlow);
  newFlow.name = newName;
  newFlow.description = newDescription;
  newFlow.locked = newLocked;
  return newFlow;
};

const buildInvalidNameList = (
  allFlows: FlowType[] | undefined,
  currentFlowName: string | undefined,
): string[] => {
  if (!allFlows) return [];
  const names = allFlows.map((f) => f?.name ?? "");
  return names.filter((n) => n !== (currentFlowName ?? ""));
};

const isSaveDisabled = (
  flow: FlowType | undefined,
  invalidNameList: string[],
  name: string,
  description: string,
  locked: boolean,
): boolean => {
  if (!flow) return true;
  const isNameChangedAndValid =
    !invalidNameList.includes(name) && flow.name !== name;
  const isDescriptionChanged = flow.description !== description;
  const isLockedChanged = flow.locked !== locked;
  return !(isNameChangedAndValid || isDescriptionChanged || isLockedChanged);
};

const FlowSettingsComponent = ({
  flowData,
  close,
  open,
}: FlowSettingsComponentProps): JSX.Element => {
  const currentFlow = useFlowStore((state) =>
    flowData ? undefined : state.currentFlow,
  );
  const setCurrentFlow = useFlowStore((state) => state.setCurrentFlow);
  const flows = useFlowsManagerStore((state) => state.flows);
  const flow = flowData ?? currentFlow;
  const [name, setName] = useState(flow?.name ?? "");
  const [description, setDescription] = useState(flow?.description ?? "");
  const [locked, setLocked] = useState<boolean>(flow?.locked ?? false);
  const [isSaving, setIsSaving] = useState(false);
  const [disableSave, setDisableSave] = useState(true);
  const formRef = useRef<HTMLFormElement>(null);
  const editableFlow = canEditFlow(flow);
  const saveFlow = useSaveFlow();

  useEffect(() => {
    setName(flow?.name ?? "");
    setDescription(flow?.description ?? "");
    setLocked(flow?.locked ?? false);
  }, [flow?.name, flow?.description, flow?.endpoint_name, open]);

  async function handleSubmit(
    event?: React.FormEvent<HTMLFormElement>,
  ): Promise<void> {
    if (event) event.preventDefault();
    if (!editableFlow) {
      close();
      return;
    }
    if (!flow) {
      return;
    }

    setIsSaving(true);
    try {
      const newFlow = updateFlowWithFormValues(flow, name, description, locked);
      if (flowData) {
        await saveFlow(newFlow);
      } else {
        setCurrentFlow(newFlow);
      }
      close();
    } finally {
      setIsSaving(false);
    }
  }

  const submitForm = () => {
    formRef.current?.requestSubmit();
  };

  const [nameLists, setNameList] = useState<string[]>([]);

  useEffect(() => {
    setNameList(buildInvalidNameList(flows, flow?.name));
  }, [flows]);

  useEffect(() => {
    setDisableSave(isSaveDisabled(flow, nameLists, name, description, locked));
  }, [nameLists, flow, description, name, locked]);
  return (
    <Form.Root onSubmit={handleSubmit} ref={formRef}>
      <div className="flex flex-col gap-4">
        {!editableFlow && (
          <div className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
            You have read-only access to this flow.
          </div>
        )}
        <div className="flex flex-col gap-2">
          <EditFlowSettings
            invalidNameList={nameLists}
            name={name}
            description={description}
            setName={setName}
            setDescription={setDescription}
            submitForm={submitForm}
            locked={locked}
            setLocked={setLocked}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            data-testid="cancel-flow-settings"
            type="button"
            onClick={() => close()}
          >
            Cancel
          </Button>
          <Form.Submit asChild>
            <Button
              variant="default"
              size="sm"
              data-testid="save-flow-settings"
              loading={isSaving}
              disabled={!editableFlow || disableSave}
            >
              Save
            </Button>
          </Form.Submit>
        </div>
      </div>
    </Form.Root>
  );
};

export default FlowSettingsComponent;
