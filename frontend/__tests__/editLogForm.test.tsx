import { fireEvent, render, screen } from "@testing-library/react";
import { EditLogForm } from "../components/EditLogForm";
import { composeEditInput, fieldsFromLog } from "../lib/editLog";

describe("fieldsFromLog / composeEditInput", () => {
  it("prefills from food_event when present", () => {
    const fields = fieldsFromLog({
      food_name: "eggs",
      food_event: {
        food: "eggs",
        brand: "Vital Farms",
        preparation: "scrambled",
        amount: 2,
        unit: "count",
        variant_tags: [{ type: "style", value: "large" }],
      },
    });
    expect(fields.food).toBe("eggs");
    expect(fields.brand).toBe("Vital Farms");
    expect(fields.preparation).toBe("scrambled");
    expect(fields.amount).toBe("2");
    expect(fields.unit).toBe("count");
    expect(fields.variant).toBe("large");
    expect(composeEditInput(fields)).toContain("eggs");
    expect(composeEditInput(fields)).toContain("Vital Farms");
  });

  it("falls back to food_name when food_event is missing", () => {
    const fields = fieldsFromLog({ food_name: "coffee" });
    expect(fields.food).toBe("coffee");
    expect(composeEditInput(fields)).toBe("coffee");
  });
});

describe("EditLogForm", () => {
  const fields = {
    food: "eggs",
    brand: "",
    variant: "",
    preparation: "",
    amount: "1",
    unit: "count",
  };

  it("labels every field and is keyboard-operable", () => {
    const onSave = jest.fn();
    const onCancel = jest.fn();
    const onChange = jest.fn();
    render(
      <EditLogForm
        logId="abc"
        foodName="eggs"
        fields={fields}
        onChange={onChange}
        onSave={onSave}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByRole("heading", { name: /edit eggs/i })).toBeInTheDocument();
    expect(screen.getByLabelText("Food")).toHaveValue("eggs");
    expect(screen.getByLabelText("Amount")).toHaveValue("1");
    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^cancel$/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Food"), {
      target: { value: "toast" },
    });
    expect(onChange).toHaveBeenCalled();

    fireEvent.keyDown(screen.getByRole("form"), { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();

    fireEvent.submit(screen.getByRole("form"));
    expect(onSave).toHaveBeenCalled();
  });
});
