import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import "./load-env";

function formatAxeViolations(
  violations: Awaited<ReturnType<AxeBuilder["analyze"]>>["violations"],
): string {
  return violations
    .map(
      (v) =>
        `${v.id} (${v.impact ?? "n/a"}): ${v.help}\n${v.nodes
          .slice(0, 5)
          .map((n) => `  ${n.html}`)
          .join("\n")}`,
    )
    .join("\n\n---\n\n");
}

test("Sign in page is accessible", async ({ page }) => {
  await page.goto("/login");
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations, formatAxeViolations(violations)).toEqual([]);
});

test("main app page is accessible", async ({ page }) => {
  const email = process.env.TEST_USER_EMAIL;
  const password = process.env.TEST_USER_PASSWORD;
  if (!email || !password) {
    throw new Error(
      "Missing TEST_USER_EMAIL or TEST_USER_PASSWORD. Create frontend/.env.test with those keys (gitignored).",
    );
  }

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /^Sign in$/i }).click();
  await expect(page).toHaveURL("/");
  await expect(page.locator("#main-content")).toBeVisible({ timeout: 15000 });

  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(violations, formatAxeViolations(violations)).toEqual([]);
});

test.describe("logged-in food log", () => {
  test.beforeEach(async ({ page }) => {
    const email = process.env.TEST_USER_EMAIL;
    const password = process.env.TEST_USER_PASSWORD;
    if (!email || !password) {
      throw new Error(
        "Missing TEST_USER_EMAIL or TEST_USER_PASSWORD. Create frontend/.env.test with those keys (gitignored).",
      );
    }

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /^Sign in$/i }).click();
    await expect(page).toHaveURL("/");
  });

  test("user can log a food and see it in the log", async ({ page }) => {
    await page.getByLabel(/type it instead/i).fill("two eggs scrambled");
    await page.getByRole("button", { name: /^Log food$/i }).click();

    const loggedStatus = page
      .getByRole("status")
      .filter({ hasText: /Logged/i });
    const clarificationHeading = page.getByRole("heading", {
      name: /^(Unsure|Less Sure)$/i,
    });
    const yesLogIt = page.getByRole("button", { name: /yes, log it/i });
    const alternativeButtons = page.getByRole("button", {
      name: /^Log .+ instead$/i,
    });

    await Promise.race([
      loggedStatus.waitFor({ state: "visible", timeout: 30000 }),
      clarificationHeading.waitFor({ state: "visible", timeout: 30000 }),
    ]);

    if (!(await loggedStatus.isVisible())) {
      const n = await alternativeButtons.count();
      let choseAlternative = false;
      for (let i = 0; i < n; i++) {
        const label = await alternativeButtons
          .nth(i)
          .getAttribute("aria-label");
        if (label && /egg/i.test(label)) {
          await alternativeButtons.nth(i).click();
          choseAlternative = true;
          break;
        }
      }
      if (!choseAlternative && n > 0) {
        await alternativeButtons.first().click();
        choseAlternative = true;
      }
      if (!choseAlternative) {
        await yesLogIt.click();
      }
      await expect(loggedStatus).toBeVisible({ timeout: 30000 });
    }

    await page.getByRole("button", { name: /Today's logs/i }).click();

    const logTable = page.getByRole("table", {
      name: /Today's food log entries/i,
    });
    const foodCells = logTable.locator("tbody tr td:nth-child(1)");
    await expect(foodCells.filter({ hasText: /egg/i }).first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("shows error message when backend cannot parse input", async ({
    page,
  }) => {
    await page.route("**/food/parse", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ error: "Could not parse" }),
      });
    });

    await page.getByLabel(/Type it instead/i).fill("asdf");
    await page.getByRole("button", { name: /^Log Food$/i }).click();

    await expect(page.getByRole("status")).toContainText(
      "I couldn't understand that. Please try saying something more specific.",
      { timeout: 10000 },
    );
  });

  test("Yes, log it saves the headline match without re-parsing", async ({
    page,
  }) => {
    await page.route("**/food/parse", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          confidence: "medium",
          food: "banana",
          brand: null,
          serving_label: "1 banana",
          serving_size: "1 banana",
          calories: 122,
          macronutrients: {
            protein: 1.5,
            carbohydrates: 31,
            fats: 0.4,
            sugar: 17,
          },
          reasoning: "Several banana entries match",
          candidates: [
            {
              fdc_id: "other",
              name: "Bananas, dehydrated",
              calories: 94.08,
              protein: 1,
              carbs: 24,
              fat: 0.2,
              serving_label: "100 g",
            },
          ],
        }),
      });
    });

    let logBody: Record<string, unknown> | null = null;
    await page.route("**/food", async (route) => {
      const req = route.request();
      if (req.method() !== "POST" || req.url().includes("/food/parse")) {
        await route.continue();
        return;
      }
      logBody = JSON.parse(req.postData() || "{}") as Record<string, unknown>;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          message: "Food logged successfully",
          id: "test-log-id",
          parsed: {
            food: logBody.food_name,
            calories: logBody.calories,
            confidence: "high",
          },
        }),
      });
    });

    await page.getByLabel(/Type it instead/i).fill("banana");
    await page.getByRole("button", { name: /^Log Food$/i }).click();

    await expect(
      page.getByRole("heading", { name: /^(Unsure|Less Sure)$/i }),
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/1 banana/i)).toBeVisible();
    await expect(page.getByText(/122 cal/i).first()).toBeVisible();

    await page.getByRole("button", { name: /yes, log it/i }).click();

    await expect(page.getByRole("status").filter({ hasText: /Logged/i })).toBeVisible(
      { timeout: 10000 },
    );
    expect(logBody).not.toBeNull();
    expect(logBody?.resolved).toBe(true);
    expect(logBody?.calories).toBe(122);
    expect(logBody?.food_name).toMatch(/banana/i);
    expect(logBody?.quantity).toBe("1 banana");
    expect(logBody?.raw_input).toBe("banana");
  });

  test("shows clarification UI on low confidence parse", async ({ page }) => {
    await page.route("**/food/parse", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          confidence: "medium",
          food: "eggs",
          serving_size: "some",
          alternatives: ["scrambled eggs", "fried eggs"],
          reasoning: "Could be several egg preparations",
        }),
      });
    });

    await page.getByLabel(/Type it instead/i).fill("some eggs");
    await page.getByRole("button", { name: /^Log Food$/i }).click();

    await expect(
      page.getByRole("heading", { name: /^(Unsure|Less Sure)$/i }),
    ).toBeVisible({ timeout: 10000 });
  });

  test("tap-to-edit form is labeled and accessible", async ({ page }) => {
    await page.route("**/food/**/today", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            _id: "507f1f77bcf86cd799439011",
            food_name: "eggs",
            calories: 150,
            protein: 12,
            carbs: 1,
            fat: 10,
            quantity: "2",
            raw_input: "two eggs",
            logged_at: new Date().toISOString(),
            food_event: {
              food: "eggs",
              brand: null,
              preparation: "scrambled",
              amount: 2,
              unit: "count",
            },
          },
        ]),
      });
    });
    await page.route("**/food/**/summary", async (route) => {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          calories: 150,
          protein: 12,
          carbs: 1,
          fat: 10,
          nutrients: {},
          entry_count: 1,
        }),
      });
    });

    await page.reload();
    await page.getByRole("button", { name: /Today's logs/i }).click();
    await page.getByRole("button", { name: /Edit eggs/i }).first().click();
    await expect(page.getByRole("heading", { name: /Edit eggs/i })).toBeVisible();
    await expect(page.getByLabel("Food")).toHaveValue("eggs");
    await expect(page.getByLabel("Preparation")).toHaveValue("scrambled");
    await expect(page.getByLabel("Amount")).toHaveValue("2");

    const { violations } = await new AxeBuilder({ page })
      .include("form")
      .analyze();
    expect(violations, formatAxeViolations(violations)).toEqual([]);
  });
});
