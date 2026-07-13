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

export interface ConsumerConformanceExecutionErrorOptions {
  readonly suiteId: string;
  readonly caseId: string;
  readonly path: string;
  readonly stepIndex: number | null;
  readonly cause: unknown;
}

export class ConsumerConformanceExecutionError extends Error {
  readonly suiteId: string;
  readonly caseId: string;
  readonly path: string;
  readonly stepIndex: number | null;
  readonly cause: unknown;
  teardownCause?: unknown;

  constructor(options: ConsumerConformanceExecutionErrorOptions) {
    const reason = errorMessage(options.cause);
    super(
      `Consumer conformance execution failed for ${options.suiteId}/${options.caseId} at ${options.path}: ${reason}`,
    );
    this.name = "ConsumerConformanceExecutionError";
    this.suiteId = options.suiteId;
    this.caseId = options.caseId;
    this.path = options.path;
    this.stepIndex = options.stepIndex;
    this.cause = options.cause;
  }

  attachTeardownCause(cause: unknown): void {
    this.teardownCause = cause;
    this.message += `; adapter teardown also failed: ${errorMessage(cause)}`;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
