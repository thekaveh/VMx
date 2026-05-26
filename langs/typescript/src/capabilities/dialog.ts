// Dialog / form capability contracts. See spec/14-capabilities.md §Dialog / form.

export interface IClosable {
  canClose(): boolean;
  close(): void;
}

export interface IApprovable {
  canApprove(): boolean;
  approve(): void;
}

export interface ICancelable {
  canCancel(): boolean;
  cancel(): void;
}
