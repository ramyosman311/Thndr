import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  listNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      listNotifications: mocks.listNotifications,
      markNotificationRead: mocks.markNotificationRead,
      markAllNotificationsRead: mocks.markAllNotificationsRead,
    },
  };
});

import NotificationsPage from "@/app/notifications/page";

const CRITICAL_NOTIF = {
  id: "n1",
  category: "RECOMMENDATION_ALERT",
  severity: "CRITICAL",
  title: "الأسهم الفردية: تجاوز الحد الأقصى المسموح به",
  message: "الأسهم الفردية تجاوزت الحد الأقصى المسموح به. يوصى بتقليل الاستثمار بحوالي 500.00.",
  target_category: "الأسهم الفردية",
  target_asset: null,
  action: "REVIEW_RECOMMENDATIONS",
  read: false,
  created_at: "2026-01-01T10:00:00Z",
};

const WARNING_NOTIF = {
  id: "n2",
  category: "ALLOCATION_ALERT",
  severity: "WARNING",
  title: "ETEL: تجاوز نسبة التنبيه المحددة",
  message: "نسبة ETEL الحالية 22.00% تجاوزت الحد الذي حددته للتنبيه (20.00%).",
  target_category: "ETEL",
  target_asset: null,
  action: "REVIEW_DISTRIBUTION",
  read: false,
  created_at: "2026-01-01T09:00:00Z",
};

const INFO_NOTIF = {
  id: "n3",
  category: "PRICE_ALERT",
  severity: "INFO",
  title: "ETEL: تم الوصول للسعر المستهدف",
  message: "تم الوصول إلى السعر المحدد لسهم ETEL (58.50).",
  target_category: null,
  target_asset: "ETEL",
  action: "OPEN_ASSET",
  read: true,
  created_at: "2026-01-01T08:00:00Z",
};

describe("NotificationsPage", () => {
  it("shows a loading state, then the list with correct severities and Arabic copy", async () => {
    mocks.listNotifications.mockResolvedValue({
      unread_count: 2,
      notifications: [CRITICAL_NOTIF, WARNING_NOTIF, INFO_NOTIF],
    });

    render(<NotificationsPage />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(CRITICAL_NOTIF.title)).toBeInTheDocument();
    });
    expect(screen.getByText(WARNING_NOTIF.title)).toBeInTheDocument();
    expect(screen.getByText(INFO_NOTIF.title)).toBeInTheDocument();
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("WARNING")).toBeInTheDocument();
    expect(screen.getByText("INFO")).toBeInTheDocument();
  });

  it("shows an empty state with no notifications", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 0, notifications: [] });

    render(<NotificationsPage />);
    await waitFor(() => {
      expect(screen.getByText("لا توجد إشعارات جديدة")).toBeInTheDocument();
    });
  });

  it("shows a clear error state with retry on failure", async () => {
    mocks.listNotifications.mockRejectedValue(new ApiError("server", 500, "حدث خطأ في الخادم."));

    render(<NotificationsPage />);
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("marks a single notification as read and updates its display without affecting others", async () => {
    mocks.listNotifications.mockResolvedValue({
      unread_count: 2,
      notifications: [CRITICAL_NOTIF, WARNING_NOTIF],
    });
    mocks.markNotificationRead.mockResolvedValue({ ...CRITICAL_NOTIF, read: true });

    render(<NotificationsPage />);
    await waitFor(() => expect(screen.getByText(CRITICAL_NOTIF.title)).toBeInTheDocument());

    const user = userEvent.setup();
    const markReadButtons = screen.getAllByRole("button", { name: "تحديد كمقروء" });
    await user.click(markReadButtons[0]);

    await waitFor(() => {
      expect(mocks.markNotificationRead).toHaveBeenCalledWith("n1");
    });
    // The second notification's own mark-as-read button must remain.
    expect(screen.getAllByRole("button", { name: "تحديد كمقروء" }).length).toBe(1);
  });

  it("marks all notifications as read via the bulk action", async () => {
    mocks.listNotifications.mockResolvedValue({
      unread_count: 2,
      notifications: [CRITICAL_NOTIF, WARNING_NOTIF],
    });
    mocks.markAllNotificationsRead.mockResolvedValue({
      unread_count: 0,
      notifications: [
        { ...CRITICAL_NOTIF, read: true },
        { ...WARNING_NOTIF, read: true },
      ],
    });

    render(<NotificationsPage />);
    await waitFor(() => expect(screen.getByText(CRITICAL_NOTIF.title)).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "تحديد الكل كمقروء" }));

    await waitFor(() => {
      expect(mocks.markAllNotificationsRead).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.queryAllByRole("button", { name: "تحديد كمقروء" }).length).toBe(0);
    });
  });

  it("renders a contextual navigation link for a recommendation-sourced notification", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 1, notifications: [CRITICAL_NOTIF] });

    render(<NotificationsPage />);
    await waitFor(() => expect(screen.getByText(CRITICAL_NOTIF.title)).toBeInTheDocument());

    const link = screen.getByRole("link", { name: /مراجعة التوصيات/ });
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders a contextual navigation link to the distribution screen for an allocation alert", async () => {
    mocks.listNotifications.mockResolvedValue({ unread_count: 1, notifications: [WARNING_NOTIF] });

    render(<NotificationsPage />);
    await waitFor(() => expect(screen.getByText(WARNING_NOTIF.title)).toBeInTheDocument());

    const link = screen.getByRole("link", { name: /مراجعة التوزيع/ });
    expect(link).toHaveAttribute("href", "/allocation");
  });
});
