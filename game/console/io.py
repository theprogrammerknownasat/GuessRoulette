specific_input = 0
general_input_0 = 0
general_input_1 = 0

out_0 = 0
out_1 = 0
out_2 = 0

if specific_input:
    if general_input_0 and general_input_1:
        pass

    if general_input_0:
        out_1 = 1
    elif general_input_1:
        out_2 = 1
    else:
        out_0 = 1

else:
    pass
