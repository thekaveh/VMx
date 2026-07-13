export interface ConsumerConformanceValidationIssue {
  readonly path: string;
  readonly keyword: string;
  readonly message: string;
  readonly schemaPath: string;
}

export class ConsumerConformanceValidationError extends Error {
  readonly issues: readonly ConsumerConformanceValidationIssue[];

  constructor(issues: readonly ConsumerConformanceValidationIssue[]) {
    const details = issues
      .map((issue) => `- ${issue.path}: ${issue.message}`)
      .join("\n");
    super(`Consumer conformance validation failed:\n${details}`);
    this.name = "ConsumerConformanceValidationError";
    this.issues = issues;
  }
}
