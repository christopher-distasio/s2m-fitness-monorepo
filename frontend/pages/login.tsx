import Head from "next/head";
import { useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useRouter } from "next/router";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState("");
  const router = useRouter();

  async function handleSubmit() {
    const { error } = isRegister
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });

    if (error) {
      setError(error.message);
    } else {
      router.push("/");
    }
  }

  const title = isRegister ? "S2M — Create account" : "S2M — Sign in";

  return (
    <>
      <Head>
        <title>{title}</title>
      </Head>
      <main className="min-h-screen bg-blue-700 flex items-center justify-center px-4">
        <div className="bg-white/15 border border-white/25 rounded-xl p-8 w-full max-w-sm shadow-lg backdrop-blur-sm">
          <h1 className="text-2xl font-bold text-white mb-6">
            {isRegister ? "Create account" : "Sign in"}
          </h1>
          <label htmlFor="login-email" className="block text-sm font-semibold text-white mb-1">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder:text-white/70 mb-4 focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
          />
          <label htmlFor="login-password" className="block text-sm font-semibold text-white mb-1">
            Password
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder:text-white/70 mb-3 focus:outline-none focus:ring-2 focus:ring-white focus:border-transparent"
          />
          {error && (
            <p role="alert" className="text-red-200 text-sm mb-3 font-medium">
              {error}
            </p>
          )}
          <button
            type="button"
            onClick={handleSubmit}
            className="w-full py-2.5 bg-white text-blue-900 font-semibold rounded-lg hover:bg-blue-50 transition-colors focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700"
          >
            {isRegister ? "Register" : "Sign in"}
          </button>
          <button
            type="button"
            onClick={() => setIsRegister(!isRegister)}
            className="w-full mt-3 py-2 text-white text-sm font-medium rounded-lg border border-white/35 hover:bg-white/10 transition-colors focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700"
          >
            {isRegister
              ? "Already have an account? Sign in"
              : "Need an account? Sign up"}
          </button>
          <button
            type="button"
            onClick={() => router.push("/demo")}
            className="w-full mt-3 py-2.5 bg-blue-900 text-white text-sm font-semibold rounded-lg hover:bg-blue-950 border border-blue-950 transition-colors focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-blue-700"
          >
            Try Demo (Currently a static display)
          </button>
        </div>
      </main>
    </>
  );
}
