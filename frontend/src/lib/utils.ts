import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Conditional className composer used by the ported workbench components.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
