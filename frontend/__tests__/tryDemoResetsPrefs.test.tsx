import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const mockSignIn = jest.fn();
const mockPush = jest.fn();

jest.mock("../lib/supabaseClient", () => ({
  supabase: {
    auth: {
      signInWithPassword: (...args: unknown[]) => mockSignIn(...args),
    },
  },
}));

jest.mock("next/router", () => ({
  useRouter: () => ({ push: mockPush }),
}));

import Login from "../pages/login";

const DEMO_USER_ID = "c0daaa18-4a82-4022-be8e-e21224683f88";

test("Try Demo signs in then PUTs empty dietary preferences", async () => {
  process.env.NEXT_PUBLIC_GUEST_EMAIL = "demo@example.com";
  process.env.NEXT_PUBLIC_GUEST_PASSWORD = "demo-password";

  mockSignIn.mockResolvedValue({
    data: { session: { user: { id: DEMO_USER_ID } } },
    error: null,
  });

  const fetchMock = jest.fn().mockResolvedValue({ ok: true });
  const originalFetch = global.fetch;
  global.fetch = fetchMock as unknown as typeof fetch;

  try {
    render(<Login />);
    fireEvent.click(screen.getByRole("button", { name: /try demo/i }));

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith({
        email: "demo@example.com",
        password: "demo-password",
      });
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://localhost:8000/user/${DEMO_USER_ID}/dietary-preferences`,
    );
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.tier_1.allergens.egg.enabled).toBe(false);
    expect(body.tier_1.allergens.milk.enabled).toBe(false);
    expect(body.tier_1.lactose_free).toBe(false);
    expect(mockPush).toHaveBeenCalledWith("/");
  } finally {
    global.fetch = originalFetch;
  }
});
