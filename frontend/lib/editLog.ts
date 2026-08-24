export type EditLogFields = {
  food: string;
  brand: string;
  variant: string;
  preparation: string;
  amount: string;
  unit: string;
};

export type EditableLog = {
  food_name?: string;
  quantity?: string;
  food_event?: {
    food?: string | null;
    brand?: string | null;
    variant_tags?: Array<{ type?: string; value?: string }>;
    preparation?: string | null;
    amount?: number;
    unit?: string;
  } | null;
};

export function fieldsFromLog(log: EditableLog): EditLogFields {
  const event = log.food_event || {};
  const variant = (event.variant_tags || [])
    .map((tag) => tag.value)
    .filter(Boolean)
    .join(", ");
  return {
    food: event.food || log.food_name || "",
    brand: event.brand || "",
    variant,
    preparation: event.preparation || "",
    amount: event.amount != null ? String(event.amount) : "",
    unit: event.unit || "",
  };
}

export function composeEditInput(fields: EditLogFields): string {
  return [
    fields.amount,
    fields.unit,
    fields.brand,
    fields.preparation,
    fields.variant,
    fields.food,
  ]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}
