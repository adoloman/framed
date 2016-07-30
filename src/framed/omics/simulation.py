from framed.solvers import solver_instance
from framed.analysis.simulation import FBA, pFBA
from numpy import percentile


def gene2rxn(gpr, gene_exp, and_func=min, or_func=sum):

    def f_and(x):
        x2 = [xi for xi in x if xi is not None]
        return and_func(x2) if x2 else None

    def f_or(x):
        x2 = [xi for xi in x if xi is not None]
        return or_func(x2) if x2 else None

    level = f_or([f_and([gene_exp[gene]
                         for gene in protein.genes if gene in gene_exp])
                  for protein in gpr.proteins])

    return level


def gene_to_reaction_expression(model, gene_exp, and_func=min, or_func=sum):
    rxn_exp = {}
    for r_id, gpr in model.gpr_associations.items():
        if gpr is not None:
            level = gene2rxn(gpr, gene_exp, and_func, or_func)
            if level is not None:
                rxn_exp[r_id] = level
    return rxn_exp


def GIMME(model, gene_exp, cutoff=25, growth_frac=0.9, constraints=None, parsimonious=False):
    rxn_exp = gene_to_reaction_expression(model, gene_exp, or_func=max)
    threshold = percentile(rxn_exp.values(), cutoff)
    coeffs = {r_id: threshold-val for r_id, val in rxn_exp.items() if val < threshold}

    solver = solver_instance()
    solver.build_problem(model)

    wt_solution = FBA(model, constraints=constraints, solver=solver)

    if not constraints:
        constraints = {}

    biomass = model.detect_biomass_reaction()
    constraints[biomass] = (growth_frac * wt_solution.values[biomass], None)

    if not parsimonious:
        solution = solver.solve_lp(coeffs, minimize=True, constraints=constraints)

    else:
        for r_id in model.reactions:
            if model.reactions[r_id].reversible:
                pos, neg = r_id + '+', r_id + '-'
                solver.add_variable(pos, 0, None, persistent=False, update_problem=False)
                solver.add_variable(neg, 0, None, persistent=False, update_problem=False)
        solver.update()

        for r_id in model.reactions:
            if model.reactions[r_id].reversible:
                pos, neg = r_id + '+', r_id + '-'
                solver.add_constraint('c' + pos, [(r_id, -1), (pos, 1)], '>', 0, persistent=False, update_problem=False)
                solver.add_constraint('c' + neg, [(r_id, 1), (neg, 1)], '>', 0, persistent=False, update_problem=False)
        solver.update()

        objective = dict()
        for r_id, val in coeffs.items():
            if model.reactions[r_id].reversible:
                pos, neg = r_id + '+', r_id + '-'
                objective[pos] = val
                objective[neg] = val
            else:
                objective[r_id] = val

        pre_solution = solver.solve_lp(objective, minimize=True, constraints=constraints)
        solver.add_constraint('obj', objective.items(), '=', pre_solution.fobj)
        objective = dict()

        for r_id in model.reactions:
            if model.reactions[r_id].reversible:
                pos, neg = r_id + '+', r_id + '-'
                objective[pos] = 1
                objective[neg] = 1
            else:
                objective[r_id] = 1

        solution = solver.solve_lp(objective, minimize=True, constraints=constraints)
        solver.remove_constraint('obj')
        solution.pre_solution = pre_solution

    return solution


def eflux(model, gene_exp, scale_rxn, scale_value, constraints=None, parsimonious=False):

    rxn_exp = gene_to_reaction_expression(model, gene_exp)
    max_exp = max(rxn_exp.values())
    bounds = {}

    for r_id, (lb, ub) in model.bounds.items():
        val = rxn_exp[r_id] / max_exp if r_id in rxn_exp else 1
        lb2 = -val if lb is None or lb < 0 else 0
        ub2 = val if ub is None or ub > 0 else 0
        bounds[r_id] = (lb2, ub2)

    if constraints:
        for r_id, x in constraints.items():
            lb, ub = x if isinstance(x, tuple) else (x, x)            
            lb2 = -1 if lb is None or lb < 0 else 0
            ub2 = 1 if ub is None or ub > 0 else 0
            bounds[r_id] = (lb2, ub2)

    if parsimonious:
        sol = pFBA(model, constraints=bounds)
    else:
        sol = FBA(model, constraints=bounds)

    k = abs(scale_value / sol.values[scale_rxn])
    for r_id, val in sol.values.items():
        sol.values[r_id] = val * k

    return sol

