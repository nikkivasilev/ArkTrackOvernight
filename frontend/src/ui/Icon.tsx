type Props = {
  /** Material Symbols Outlined ligature name, e.g. "settings", "sensors", "warning". */
  name: string;
  /** Render the filled variant. */
  filled?: boolean;
  /** Optical size in px (drives font-size + opsz axis). Default 20. */
  size?: number;
  /** Optical weight axis (100–700). Default 400. */
  weight?: number;
  className?: string;
};

/**
 * Thin wrapper over the Material Symbols Outlined icon font (loaded in index.html).
 * Sizes via inline font-size so it tracks the `size` prop; color inherits from
 * the surrounding text color (use text-* utilities to tint).
 */
export function Icon({ name, filled = false, size = 20, weight = 400, className = "" }: Props) {
  return (
    <span
      aria-hidden="true"
      className={`material-symbols-outlined${filled ? " fill" : ""} ${className}`}
      style={{
        fontSize: size,
        fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'opsz' ${size}, 'wght' ${weight}, 'GRAD' 0`,
      }}
    >
      {name}
    </span>
  );
}
