interface MetricBoxProps {
  label: string;
  value: string | number;
  subtext?: string;
  color?: "green" | "red" | "yellow" | "blue" | "default";
}

const COLOR_MAP = {
  green: "text-green-400",
  red: "text-red-400",
  yellow: "text-yellow-400",
  blue: "text-blue-400",
  default: "text-white",
};

export default function MetricBox({ label, value, subtext, color = "default" }: MetricBoxProps) {
  return (
    <div className="rounded-lg border border-[#2a2a2a] bg-[#111] p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-[#888]">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${COLOR_MAP[color]}`}>{value}</p>
      {subtext && <p className="mt-1 text-xs text-[#666]">{subtext}</p>}
    </div>
  );
}
