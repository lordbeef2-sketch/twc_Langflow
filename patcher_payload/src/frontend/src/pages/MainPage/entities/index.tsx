import type { FlowType } from "../../../types/flow";

export type FolderType = {
  name: string;
  description: string;
  id?: string | null;
  parent_id: string | null;
  flows: FlowType[];
  components: string[];
  readonly?: boolean;
  is_shared_folder?: boolean;
};

export type PaginatedFolderType = {
  folder: {
    name: string;
    description: string;
    id?: string | null;
    parent_id: string | null;
    components: string[];
    readonly?: boolean;
    is_shared_folder?: boolean;
  };
  flows: {
    items: FlowType[];
    total: number;
    page: number;
    size: number;
    pages: number;
  };
};

export type AddFolderType = {
  name: string;
  description: string;
  id?: string | null;
  parent_id: string | null;
  flows?: string[];
  components?: string[];
};

export type StarterProjectsType = {
  name?: string;
  description?: string;
  flows?: FlowType[];
  id: string;
  parent_id: string;
};
