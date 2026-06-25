interface Option<T> {
  value: T;
  label: string;
  sub?: string;
}

interface Props<T extends string | number> {
  legend: string;
  options: Option<T>[];
  value: T;
  onChange: (v: T) => void;
  columns?: number;
}

// A labelled group of large, tappable chips. Used for duration, road profile,
// tolerance and direction. Built as real radio inputs for keyboard and screen
// reader support, styled via the .chip classes.
export function ChipGroup<T extends string | number>({
  legend,
  options,
  value,
  onChange,
  columns,
}: Props<T>) {
  return (
    <fieldset className="chip-group">
      <legend className="chip-legend">{legend}</legend>
      <div
        className="chip-row"
        style={columns ? { gridTemplateColumns: `repeat(${columns}, 1fr)` } : undefined}
      >
        {options.map((opt) => {
          const selected = opt.value === value;
          return (
            <label
              key={String(opt.value)}
              className={`chip${selected ? " chip-on" : ""}`}
            >
              <input
                type="radio"
                name={legend}
                checked={selected}
                onChange={() => onChange(opt.value)}
              />
              <span className="chip-label">{opt.label}</span>
              {opt.sub && <span className="chip-sub">{opt.sub}</span>}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
