import { InputHTMLAttributes, forwardRef } from "react";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  className?: string;
};

export const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { className = "", ...props },
  ref
) {
  return (
    <input
      ref={ref}
      {...props}
      className={`
        h-9 w-full rounded-md border border-input bg-surface-low px-3 py-1 text-sm
        placeholder:text-text-mute
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-40
        focus-visible:border-accent
        disabled:opacity-50 disabled:cursor-not-allowed
        ${className}
      `}
    />
  );
});
