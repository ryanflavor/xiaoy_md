import { render, screen } from "@testing-library/react";

import { ErrorBanner, resolveApiError } from "@/components/ErrorBanner";
import { ApiError } from "@/services/apiClient";

describe("resolveApiError", () => {
  it("maps 401 responses to bilingual guidance", () => {
    const copy = resolveApiError(new ApiError("Missing Authorization header", 401));
    expect(copy.primaryEn).toContain("Unauthorized");
    expect(copy.primaryZh).toContain("请求未授权");
    expect(copy.helperEn).toContain("VITE_OPS_API_TOKEN");
    expect(copy.detail).toBe("Missing Authorization header");
  });

  it("handles network failures", () => {
    const copy = resolveApiError(new TypeError("Failed to fetch"));
    expect(copy.primaryEn).toContain("Cannot reach");
    expect(copy.helperZh).toContain("ops-api 服务已启动");
  });
});

describe("ErrorBanner", () => {
  it("renders bilingual messaging for ApiError", () => {
    render(<ErrorBanner error={new ApiError("Unauthorized", 403)} />);
    expect(screen.getByText(/Access forbidden/i)).toBeTruthy();
    expect(screen.getByText(/拒绝访问/)).toBeTruthy();
  });
});
