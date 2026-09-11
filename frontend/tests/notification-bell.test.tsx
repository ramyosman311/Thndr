import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  listNotifications: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listNotifications: mocks.listNotifications,
    },
  };
});

import { NotificationBell } from "@/components/notification-bell";

describe("NotificationBell", () => {
  it("shows the unread count the backend computed", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 3, notifications: [] });

    render(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByText("3")).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /الإشعارات — 3 غير مقروء/ })).toHaveAttribute(
      "href",
      "/notifications"
    );
  });

  it("shows no badge when there are no unread notifications", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 0, notifications: [] });

    render(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "الإشعارات" })).toBeInTheDocument();
    });
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("caps the displayed badge at 9+", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 15, notifications: [] });

    render(<NotificationBell />);

    await waitFor(() => {
      expect(screen.getByText("9+")).toBeInTheDocument();
    });
  });
});
