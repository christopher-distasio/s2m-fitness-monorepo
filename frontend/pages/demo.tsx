import { useRouter } from "next/router";

const SAMPLE_LOGS = [
  {
    id: "1",
    food: "Chicken breast",
    quantity: "6 oz",
    confidence: 0.9,
    reasoning: "User mentioned size reference (palm)",
    estimated_calories: 280,
  },
  {
    id: "2",
    food: "Rice",
    quantity: "1 cup",
    confidence: 0.85,
    reasoning: "Specific quantity mentioned",
    estimated_calories: 200,
  },
  {
    id: "3",
    food: "Broccoli",
    quantity: "Medium serving",
    confidence: 0.7,
    reasoning: "Vague quantity, typical serving assumed",
    estimated_calories: 55,
  },
];

export default function DemoPage() {
  const router = useRouter();
  const totalCalories = SAMPLE_LOGS.reduce(
    (sum, log) => sum + log.estimated_calories,
    0,
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-600 to-blue-800 p-4">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="text-white mb-6">
          <h1 className="text-3xl font-bold mb-2">Speak2Me Fitness</h1>
          <p className="text-blue-100">
            Voice-first food logging with AI confidence scoring
          </p>
        </div>

        {/* What is this? */}
        <div className="bg-white/10 border border-white/20 rounded-xl p-6 mb-6 backdrop-blur-sm">
          <h2 className="text-white font-semibold mb-3">
            What You&apos;re Looking At
          </h2>
          <p className="text-blue-100 text-sm mb-3">
            This is a read-only preview of how Speak2Me Fitness works.
            You&apos;ll see sample food logs with confidence scores&mdash;the
            AI&apos;s way of saying &quot;I&apos;m X% sure this is what you
            said.&quot;
          </p>
          <p className="text-blue-100 text-sm mb-3">
            High confidence (85%+)? You were specific (&quot;6 oz of
            chicken&quot;). Low confidence (60&ndash;70%)? You were vague
            (&quot;some chicken, maybe&quot;). The app will explain its reasoning
            either way.
          </p>
        </div>

        {/* Demo Badge */}
        <div className="bg-yellow-500/20 border border-yellow-500/50 rounded-lg p-3 mb-6">
          <p className="text-yellow-100 text-sm font-semibold">
            📖 Read-Only Demo
          </p>
          <p className="text-yellow-100 text-xs mt-1">
            Buttons are disabled.{" "}
            <a
              href="https://www.speak2mefitness.com/login"
              className="underline hover:text-white font-semibold"
            >
              Sign up
            </a>{" "}
            to actually log meals and save data.
          </p>
        </div>

        {/* Daily Summary */}
        <div className="bg-white/10 border border-white/20 rounded-xl p-6 mb-6 backdrop-blur-sm">
          <div className="flex justify-between items-center mb-6">
            <div>
              <p className="text-blue-100 text-xs">Total Calories</p>
              <p className="text-white text-2xl font-bold">{totalCalories}</p>
            </div>
            <div>
              <p className="text-blue-100 text-xs">Daily Goal</p>
              <p className="text-white text-2xl font-bold">2000</p>
            </div>
            <div className="w-20 h-20 rounded-full bg-white/20 flex items-center justify-center">
              <p className="text-white font-bold">
                {Math.round((totalCalories / 2000) * 100)}%
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <button
            disabled
            title="Sign up to record meals with voice"
            className="w-full py-3 bg-white text-blue-700 font-semibold rounded-lg mb-3 opacity-50 cursor-not-allowed"
          >
            🎤 Record Meal
          </button>
          <button
            disabled
            title="Sign up to manually add meals"
            className="w-full py-3 bg-blue-400 text-white font-semibold rounded-lg opacity-50 cursor-not-allowed"
          >
            ➕ Add Meal
          </button>
        </div>

        {/* Food Logs */}
        <div className="space-y-4 mb-8">
          <p className="text-white text-sm font-semibold">Sample Food Logs</p>
          {SAMPLE_LOGS.map((log) => (
            <div
              key={log.id}
              className="bg-white/10 border border-white/20 rounded-lg p-4 backdrop-blur-sm"
            >
              <div className="flex justify-between items-start mb-3">
                <div className="flex-1">
                  <h3 className="text-white font-semibold">{log.food}</h3>
                  <p className="text-blue-100 text-sm">{log.quantity}</p>
                </div>
                <p className="text-white font-bold ml-4">
                  {log.estimated_calories} cal
                </p>
              </div>

              {/* Confidence Indicator */}
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1">
                  <p className="text-blue-100 text-xs">AI Confidence</p>
                  <p className="text-white text-sm font-semibold">
                    {(log.confidence * 100).toFixed(0)}%
                  </p>
                </div>
                <div className="w-full bg-white/20 rounded-full h-2">
                  <div
                    className="bg-green-400 h-2 rounded-full transition-all"
                    style={{ width: `${log.confidence * 100}%` }}
                  />
                </div>
              </div>

              <p className="text-blue-100 text-xs italic mb-3">
                &quot;{log.reasoning}&quot;
              </p>

              {/* Log Action Buttons */}
              <div className="flex gap-2">
                <button
                  disabled
                  title="Sign up to edit this log"
                  className="flex-1 py-2 bg-white/20 text-white text-sm rounded opacity-50 cursor-not-allowed"
                >
                  ✏️ Edit
                </button>
                <button
                  disabled
                  title="Sign up to delete this log"
                  className="flex-1 py-2 bg-white/20 text-white text-sm rounded opacity-50 cursor-not-allowed"
                >
                  🗑️ Delete
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* CTA */}
        <button
          onClick={() => router.push("/login")}
          className="w-full py-3 bg-white text-blue-700 font-semibold rounded-lg hover:bg-blue-50 transition-colors"
        >
          Sign Up to Get Started
        </button>
      </div>
    </div>
  );
}
