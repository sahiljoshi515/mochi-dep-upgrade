from .checks import result, tail_problem


def verify_input(value):
    return result(True, "input is valid")


def verify_output(input_value, output_value, workspace):
    problem = tail_problem(output_value.tail)
    if problem:
        return result(False, problem)
    if output_value.seconds < 0:
        return result(False, "seconds is negative")
    if output_value.complete and output_value.next.strip():
        return result(False, "a finished sync has nothing next")
    if not output_value.complete and (output_value.ok or not output_value.next.strip()):
        return result(False, "an unfinished sync is not ok and says what to do next")
    return result(True, "sync reported", ok=output_value.ok, complete=output_value.complete)
