namespace LeanGate

/-- An exact, finite resource-allocation instance.  Integers are deliberate:
the bridge from floating-point solver output must state its scaling policy. -/
structure ResourceInstance (n : Nat) where
  capacity : Fin n → Int
  profit : Fin n → Int
  budget : Int

def sumFin : {n : Nat} → (Fin n → Int) → Int
  | 0, _ => 0
  | _ + 1, values => values 0 + sumFin (fun i => values i.succ)

def objective {n : Nat} (inst : ResourceInstance n) (allocation : Fin n → Int) : Int :=
  sumFin (fun i => inst.profit i * allocation i)

def Feasible {n : Nat} (inst : ResourceInstance n)
    (allocation : Fin n → Int) : Prop :=
  (∀ i, 0 ≤ allocation i ∧ allocation i ≤ inst.capacity i) ∧
  sumFin allocation ≤ inst.budget

def checkFeasible {n : Nat} (inst : ResourceInstance n)
    (allocation : Fin n → Int) [Decidable (Feasible inst allocation)] : Bool :=
  decide (Feasible inst allocation)

/-- The executable Boolean checker cannot assert more than its proposition. -/
theorem checkFeasible_sound {n : Nat} (inst : ResourceInstance n)
    (allocation : Fin n → Int) [Decidable (Feasible inst allocation)]
    (h : checkFeasible inst allocation = true) : Feasible inst allocation := by
  exact of_decide_eq_true h

/-- A componentwise upper-bound certificate.  This is the reusable core behind
the first LeanGate example; summing/objective-specific corollaries stay explicit. -/
structure UpperBoundCertificate {n : Nat} (inst : ResourceInstance n)
    (allocation : Fin n → Int) : Prop where
  candidate_feasible : Feasible inst allocation
  profit_nonnegative : ∀ i, 0 ≤ inst.profit i

theorem objective_le_capacity {n : Nat} (inst : ResourceInstance n)
    (allocation : Fin n → Int) (hcap : ∀ i, allocation i ≤ inst.capacity i)
    (hprofit : ∀ i, 0 ≤ inst.profit i) :
    objective inst allocation ≤ objective inst inst.capacity := by
  induction n with
  | zero => exact Int.le_refl _
  | succ n ih =>
      apply Int.add_le_add
      · exact Int.mul_le_mul_of_nonneg_left (hcap 0) (hprofit 0)
      · exact ih
          { capacity := fun i => inst.capacity i.succ
            profit := fun i => inst.profit i.succ
            budget := inst.budget }
          (fun i => allocation i.succ) (fun i => hcap i.succ) (fun i => hprofit i.succ)

theorem certified_component_upper_bound {n : Nat}
    (inst : ResourceInstance n) (allocation : Fin n → Int)
    (certificate : UpperBoundCertificate inst allocation) :
    objective inst allocation ≤ objective inst inst.capacity := by
  exact objective_le_capacity inst allocation
    (fun i => (certificate.candidate_feasible.1 i).2)
    certificate.profit_nonnegative

end LeanGate
