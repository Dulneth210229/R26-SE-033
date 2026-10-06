export default function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{title}</h1>
        {subtitle && <p className="text-gray-500 dark:text-gray-400 mt-1">{subtitle}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
