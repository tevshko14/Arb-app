interface CardProps {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}

export default function Card({ title, subtitle, children, className = "" }: CardProps) {
  return (
    <div className={`rounded-lg border border-[#2a2a2a] bg-[#1a1a1a] p-5 ${className}`}>
      <div className="mb-4">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-[#888]">{title}</h3>
        {subtitle && <p className="mt-1 text-xs text-[#666]">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}
