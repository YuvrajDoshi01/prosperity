FROM public.ecr.aws/lambda/python:3.12
COPY app.py datamodel.py trader.py requirements.txt ./
ADD simulation ./simulation
RUN python3 -m pip install -r requirements.txt
# Overwrite the command by providing a different command directly in the template.
CMD ["app.lambda_handler"]