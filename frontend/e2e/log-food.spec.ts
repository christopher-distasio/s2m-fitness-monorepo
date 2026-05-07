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
});
