import LeanGate.Core.ResourceAllocation
import Std.Tactic

namespace LeanGate.Examples

def creditCapacity : LeanGate.ResourceInstance 3 where
  capacity
    | 0 => 40
    | 1 => 35
    | 2 => 25
  profit
    | 0 => 5
    | 1 => 3
    | 2 => 2
  budget := 100

def creditCandidate : Fin 3 → Int
  | 0 => 40
  | 1 => 30
  | 2 => 20

theorem creditCandidate_feasible : LeanGate.Feasible creditCapacity creditCandidate := by
  constructor
  · intro i
    refine Fin.cases ?_ (fun j => ?_) i
    · decide
    · refine Fin.cases ?_ (fun k => ?_) j
      · decide
      · refine Fin.cases ?_ (fun impossible => Fin.elim0 impossible) k
        decide
  · decide

end LeanGate.Examples
