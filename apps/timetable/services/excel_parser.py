import pandas as pd


class TimetableExcelParserService:
    def parse(self, file_path):
        dataframe = pd.read_excel(file_path)
        dataframe.columns = [str(column).strip().lower() for column in dataframe.columns]
        return dataframe
