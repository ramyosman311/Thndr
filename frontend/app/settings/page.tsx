import { SettingsIcon } from "@/components/icons";

export default function SettingsPage() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-bold text-foreground">الإعدادات</h1>
      <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-border p-8 text-center text-muted-foreground">
        <SettingsIcon width={28} height={28} />
        <div>
          <p className="text-sm font-semibold text-foreground">قريبًا</p>
          <p className="mt-1 text-xs">
            إدارة إعدادات المحفظة، الفئات الاستراتيجية، ونسب الاستهداف ستتوفر هنا في مرحلة لاحقة.
          </p>
        </div>
      </div>
    </div>
  );
}
