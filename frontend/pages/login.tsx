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

  return (
    <div className="min-h-screen bg-blue-700 flex items-center justify-center">
      <div className="bg-white/10 border border-white/20 rounded-xl p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-white mb-6">
          {isRegister ? "Create account" : "Sign in"}
        </h1>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 mb-3 focus:outline-none focus:ring-2 focus:ring-white"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          className="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/30 text-white placeholder-blue-300 mb-3 focus:outline-none focus:ring-2 focus:ring-white"
        />
        {error && <p className="text-red-300 text-sm mb-3">{error}</p>}
        <button
          onClick={handleSubmit}
          className="w-full py-2.5 bg-white text-blue-700 font-semibold rounded-lg hover:bg-blue-50 transition-colors"
        >
          {isRegister ? "Register" : "Sign in"}
        </button>
        <button
          onClick={() => setIsRegister(!isRegister)}
          className="w-full mt-3 text-blue-200 text-sm hover:text-white"
        >
          {isRegister
            ? "Already have an account? Sign in"
            : "Need an account? Sign up"}
        </button>
        <button
          onClick={() => router.push("/demo")}
          className="w-full mt-3 py-2 bg-blue-400 text-white text-sm rounded-lg hover:bg-blue-500 transition-colors"
        >
          Try Demo (A static diplay, no signup required)
        </button>
      </div>
    </div>
  );
}
